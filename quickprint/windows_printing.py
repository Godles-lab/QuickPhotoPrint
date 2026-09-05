"""Windows per-job driver settings and full-paper GDI output.

Keep the complete DEVMODE, including the driver's private borderless/media data.
DocumentProperties never receives DM_UPDATE: editing here does not change the
system printer defaults. No job is created by prepare(), inspect() or edit().
"""
import base64
import ctypes as C
from dataclasses import dataclass
import sys


class DevMode(C.Structure):
    # Fixed-width types also make the ABI/layout testable on non-Windows hosts.
    _fields_ = [('DeviceName', C.c_uint16 * 32),
                ('SpecVersion', C.c_uint16), ('DriverVersion', C.c_uint16),
                ('Size', C.c_uint16), ('DriverExtra', C.c_uint16), ('Fields', C.c_uint32)]
    _fields_ += [(name, C.c_int16) for name in (
        'Orientation', 'PaperSize', 'PaperLength', 'PaperWidth', 'Scale', 'Copies',
        'DefaultSource', 'PrintQuality', 'Color', 'Duplex', 'YResolution', 'TTOption', 'Collate')]
    _fields_ += [('FormName', C.c_uint16 * 32), ('LogPixels', C.c_uint16)]
    _fields_ += [(name, C.c_uint32) for name in (
        'BitsPerPel', 'PelsWidth', 'PelsHeight', 'DisplayFlags', 'DisplayFrequency',
        'ICMMethod', 'ICMIntent', 'MediaType', 'DitherType', 'Reserved1', 'Reserved2',
        'PanningWidth', 'PanningHeight')]


class DocInfo(C.Structure):
    _fields_ = [('size', C.c_int), ('name', C.c_wchar_p), ('output', C.c_wchar_p),
                ('datatype', C.c_wchar_p), ('flags', C.c_uint32)]


def mode_header(data):
    if len(data) < C.sizeof(DevMode):
        raise ValueError('驱动设置数据不完整，请重新打开驱动设置。')
    mode = DevMode.from_buffer_copy(data)
    if mode.Size < C.sizeof(DevMode) or mode.Size + mode.DriverExtra != len(data):
        raise ValueError('驱动设置数据不匹配，请重新打开驱动设置。')
    return mode


def compatible_mode(saved, default):
    old, new = mode_header(saved), mode_header(default)
    return (old.SpecVersion, old.DriverVersion, old.Size, old.DriverExtra, bytes(old.DeviceName)) == (
        new.SpecVersion, new.DriverVersion, new.Size, new.DriverExtra, bytes(new.DeviceName))


@dataclass(frozen=True)
class Geometry:
    dpi_x: int
    dpi_y: int
    width: int
    height: int
    offset_x: int
    offset_y: int
    printable_width: int
    printable_height: int

    def __post_init__(self):
        if min(self.dpi_x, self.dpi_y, self.width, self.height,
               self.printable_width, self.printable_height) <= 0:
            raise ValueError('驱动未返回有效的纸张和可打印区域。')

    @property
    def size_mm(self):
        return self.width * 25.4 / self.dpi_x, self.height * 25.4 / self.dpi_y

    @property
    def margins_mm(self):
        return tuple(max(0, value) for value in (
            self.offset_x * 25.4 / self.dpi_x, self.offset_y * 25.4 / self.dpi_y,
            (self.width - self.offset_x - self.printable_width) * 25.4 / self.dpi_x,
            (self.height - self.offset_y - self.printable_height) * 25.4 / self.dpi_y))

    @property
    def drawing_box(self):
        # GDI's origin is the printable area, while our image covers the paper.
        return (-self.offset_x, -self.offset_y,
                self.width - self.offset_x, self.height - self.offset_y)

    def require_size(self, width, height):
        actual_w, actual_h = self.size_mm
        if abs(actual_w - width) > 1 or abs(actual_h - height) > 1:
            raise ValueError(f'驱动纸张为 {actual_w:.1f} × {actual_h:.1f} mm，'
                             f'与预览 {width:g} × {height:g} mm 不一致，请检查驱动设置。')


@dataclass(frozen=True)
class Configuration:
    name: str
    mode: bytes
    geometry: Geometry

    def saved(self):
        return base64.b64encode(self.mode).decode('ascii')


class WindowsPrinting:
    def __init__(self):
        if sys.platform != 'win32':
            raise RuntimeError('此打印接口仅用于 Windows。')
        self.spool = C.WinDLL('winspool.drv', use_last_error=True)
        self.gdi = C.WinDLL('gdi32', use_last_error=True)
        pointer, integer, wide = C.c_void_p, C.c_int, C.c_wchar_p
        signatures = {
            'OpenPrinterW': ([wide, C.POINTER(pointer), pointer], integer),
            'ClosePrinter': ([pointer], integer),
            'DocumentPropertiesW': ([pointer, pointer, wide, pointer, pointer, C.c_uint32], C.c_long),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.spool, name); fn.argtypes = args; fn.restype = result
        signatures = {
            'CreateDCW': ([wide, wide, wide, pointer], pointer),
            'DeleteDC': ([pointer], integer),
            'GetDeviceCaps': ([pointer, integer], integer),
            'StartDocW': ([pointer, C.POINTER(DocInfo)], integer),
            'StartPage': ([pointer], integer), 'EndPage': ([pointer], integer),
            'EndDoc': ([pointer], integer), 'AbortDoc': ([pointer], integer),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.gdi, name); fn.argtypes = args; fn.restype = result

    def _mode(self, name, source=None, parent=None):
        handle = C.c_void_p()
        if not self.spool.OpenPrinterW(name, C.byref(handle), None):
            raise OSError('无法打开所选打印机，请检查连接并刷新列表。')
        try:
            size = self.spool.DocumentPropertiesW(None, handle, name, None, None, 0)
            if not C.sizeof(DevMode) <= size <= 4 * 1024 * 1024:
                raise ValueError('驱动未返回有效的打印设置。')
            output = C.create_string_buffer(size)
            input_buffer = C.create_string_buffer(source) if source is not None else None
            flags = 2 | (8 if source is not None else 0) | (4 if parent is not None else 0)
            result = self.spool.DocumentPropertiesW(parent, handle, name, output, input_buffer, flags)
            if parent is not None and result == 2:
                return None
            if result != 1:
                raise ValueError('驱动未接受打印设置，请检查纸张、介质和满幅选项。')
            header = DevMode.from_buffer(output)
            data = output.raw[:header.Size + header.DriverExtra]
            mode_header(data)
            return data
        finally:
            self.spool.ClosePrinter(handle)

    def prepare(self, name, page, width, height, saved=''):
        default = self._mode(name)
        source = default
        if saved:
            try:
                candidate = base64.b64decode(saved, validate=True)
                if not compatible_mode(candidate, default):
                    raise ValueError('driver changed')
                source = candidate
            except (ValueError, TypeError) as exc:
                raise ValueError('已保存的驱动设置不适用于当前驱动，请重新设置。') from exc
        buffer = C.create_string_buffer(source, len(source))
        dm = DevMode.from_buffer(buffer)
        # Preserve private full-bleed/media/quality settings and driver resolution.
        # Rendering DPI controls the input image only, not the driver's quality.
        native = page.size(page.Unit.Millimeter) if page is not None else None
        native_w, native_h = (native.width(), native.height()) if native else sorted((width, height))
        dm.Orientation = 2 if (width > height) != (native_w > native_h) else 1
        dm.Fields |= 0x1 | 0x2 | 0x10 | 0x100 | 0x1000  # orientation, paper, scale, copies, duplex
        dm.Fields &= ~0x10000  # The selected paper supersedes a saved form name.
        dm.Scale, dm.Copies, dm.Duplex = 100, 1, 1
        paper_id = page.windowsId() if page is not None else 0
        if paper_id > 0:
            dm.PaperSize = paper_id
            dm.PaperWidth = dm.PaperLength = 0
            dm.Fields &= ~(0x4 | 0x8)
        else:
            dm.PaperSize = 0
            dm.PaperWidth, dm.PaperLength = round(native_w * 10), round(native_h * 10)
            dm.Fields |= 0x4 | 0x8
        result = self.inspect(name, self._mode(name, buffer.raw))
        accepted = mode_header(result.mode)
        if ((accepted.Fields & 0x10 and accepted.Scale not in (0, 100)) or
                (accepted.Fields & 0x100 and accepted.Copies != 1) or
                (accepted.Fields & 0x1000 and accepted.Duplex not in (0, 1))):
            raise ValueError('驱动未保留原尺寸、单面或份数设置，请检查驱动设置。')
        result.geometry.require_size(width, height)
        return result

    def defaults(self, name):
        return self.inspect(name, self._mode(name))

    def edit(self, configuration, parent):
        data = self._mode(configuration.name, configuration.mode, parent)
        return self.inspect(configuration.name, data) if data is not None else None

    def inspect(self, name, mode):
        mode_header(mode)
        buffer = C.create_string_buffer(mode)
        dc = self.gdi.CreateDCW('WINSPOOL', name, None, buffer)
        if not dc:
            raise ValueError('无法读取驱动的可打印区域。')
        try:
            return Configuration(name, mode, self._geometry(dc))
        finally:
            self.gdi.DeleteDC(dc)

    def _geometry(self, dc):
        # LOGPIXELS X/Y, PHYSICAL WIDTH/HEIGHT/OFFSET X/Y, HORZRES/VERTRES.
        return Geometry(*(self.gdi.GetDeviceCaps(dc, index)
                          for index in (88, 90, 110, 111, 112, 113, 8, 10)))

    def print_page(self, configuration, image, copies=1, output=None):
        from PIL import ImageWin
        if not 1 <= copies <= 99:
            raise ValueError('打印份数需要为 1–99。')
        buffer = C.create_string_buffer(configuration.mode)
        dc = self.gdi.CreateDCW('WINSPOOL', configuration.name, None, buffer)
        if not dc:
            raise ValueError('无法启动 Windows 打印，请检查驱动。')
        started = False
        try:
            geometry = self._geometry(dc)
            if geometry != configuration.geometry:
                raise ValueError('驱动可打印区域已改变，本次未发送，请刷新预览后重试。')
            doc = DocInfo(C.sizeof(DocInfo), 'Quick Photo Print', output, None, 0)
            job = self.gdi.StartDocW(dc, C.byref(doc))
            if job <= 0:
                raise ValueError('Windows 未能创建打印任务。')
            started = True
            dib = ImageWin.Dib(image.convert('RGB'))
            for _ in range(copies):
                if self.gdi.StartPage(dc) <= 0:
                    raise ValueError('Windows 未能开始打印页面。')
                dib.draw(dc, geometry.drawing_box)
                if self.gdi.EndPage(dc) <= 0:
                    raise ValueError('Windows 未能提交打印页面。')
            if self.gdi.EndDoc(dc) <= 0:
                raise ValueError('Windows 未能提交打印任务。')
            started = False
            return job
        finally:
            if started:
                self.gdi.AbortDoc(dc)
            self.gdi.DeleteDC(dc)
