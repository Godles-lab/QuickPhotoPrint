"""RGB output compensation and portable ICC v2/v4 curve editing.

Apply F after PCS->device, and F^-1 before device->PCS. Keep the source
CLUT/matrix, intent-specific transforms and attribution. No native dependencies.
Format reference: https://www.color.org/specification/ICC.1-2022-05.pdf
"""
from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import cached_property, lru_cache
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import struct
import tempfile

from PIL import ImageCms

SAMPLES = 4096
MAX_PROFILE_BYTES = 128 * 1024 * 1024


def interpolate(values, x):
    pos = max(0., min(1., x)) * (len(values) - 1)
    index = min(int(pos), len(values) - 2)
    return values[index] + (values[index + 1] - values[index]) * (pos - index)


def midpoint_curve(x, offset):
    if not offset:
        return x
    x *= 255
    mid = 128 + offset
    m = 6 * ((255 - mid) / 127 - mid / 128) / 510
    a, b, ya, yb, ma, mb = ((0, 128, 0, mid, 0, m) if x <= 128
                           else (128, 255, mid, 255, m, 0))
    h = b - a
    return (ma * (b-x)**3 / (6*h) + mb * (x-a)**3 / (6*h)
            + (ya-ma*h*h/6) * (b-x)/h + (yb-mb*h*h/6) * (x-a)/h) / 255


@dataclass(frozen=True)
class ColorAdjustment:
    brightness: int = 0
    contrast: int = 0
    red: int = 0
    green: int = 0
    blue: int = 0

    def __post_init__(self):
        if any(type(v) is not int or not -50 <= v <= 50 for v in asdict(self).values()):
            raise ValueError('颜色微调数值必须在 −50 至 +50 之间。')

    @property
    def active(self):
        return any(asdict(self).values())

    def value(self, x, channel):
        x = max(0., min(1., x))
        x = midpoint_curve(x, (self.red, self.green, self.blue)[channel] * .4)
        x = midpoint_curve(x, self.brightness * .6)
        x += self.contrast / 200 * (x-.5) * 4*x*(1-x)
        return max(0., min(1., x))

    @cached_property
    def curves(self):
        return tuple(tuple(self.value(i/(SAMPLES-1), ch) for i in range(SAMPLES))
                     for ch in range(3))

    def inverse(self, x, channel):
        if not self.active:
            return x
        values = self.curves[channel]
        i = max(1, min(len(values)-1, bisect_left(values, max(0., min(1., x)))))
        return (i-1 + (x-values[i-1])/(values[i]-values[i-1]))/(len(values)-1)

    def apply(self, image):
        if not self.active:
            return image.copy()
        if image.mode != 'RGB':
            raise ValueError('颜色微调需要 RGB 图像。')
        table = [round(self.value(i/255, channel)*255) for channel in range(3) for i in range(256)]
        return image.point(table)


def profile_bytes(profile):
    if profile == 'srgb':
        return ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    path = Path(profile)
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise ValueError('ICC 文件过大，无法编辑。')
    return path.read_bytes()


@lru_cache(maxsize=16)
def _has_edit_marker(path, size, mtime_ns):
    with open(path, 'rb') as stream:
        header = stream.read(132)
        if len(header) != 132:
            return False
        count = struct.unpack_from('>I', header, 128)[0]
        if count > 4096:
            return False
        table = stream.read(count*12)
    return any(table[i:i+4] == b'qpet' for i in range(0, len(table), 12))


def has_edit_marker(profile):
    if not profile or profile == 'srgb':
        return False
    path = Path(profile).resolve()
    stat = path.stat()
    return _has_edit_marker(str(path), stat.st_size, stat.st_mtime_ns)


def read_tags(data):
    if (len(data) < 132 or len(data) > MAX_PROFILE_BYTES or data[36:40] != b'acsp'
            or data[16:20] != b'RGB ' or data[20:24] not in (b'XYZ ', b'Lab ')
            or data[8] not in (2, 4) or data[12:16] not in (b'prtr', b'mntr', b'scnr', b'spac')):
        raise ValueError('编辑器需要 ICC v2/v4 的 RGB 设备配置文件。')
    size, count = struct.unpack_from('>I', data)[0], struct.unpack_from('>I', data, 128)[0]
    if size != len(data) or count > 4096 or 132+12*count > len(data):
        raise ValueError('ICC 文件头或标签表无效。')
    tags = {}
    for i in range(count):
        sig, offset, length = struct.unpack_from('>4sII', data, 132+i*12)
        if sig in tags or offset < 132+12*count or offset % 4 or length < 8 or offset+length > size:
            raise ValueError('ICC 标签数据无效。')
        tags[sig] = data[offset:offset+length]
    # These have precedence over A2B/B2A; never silently export unedited paths.
    if any(sig.startswith((b'D2B', b'B2D')) for sig in tags):
        raise ValueError('这个 ICC 使用浮点色彩转换表，暂不支持另存微调版。')
    return tags


def curve_reader(data, offset=0):
    def need(length):
        if offset+length > len(data):
            raise ValueError('ICC 曲线不完整。')
    need(12)
    kind = data[offset:offset+4]
    if kind == b'curv':
        count = struct.unpack_from('>I', data, offset+8)[0]
        need(12+count*2)
        if count == 0:
            return lambda x: x, 12
        if count == 1:
            gamma = struct.unpack_from('>H', data, offset+12)[0]/256
            if gamma <= 0:
                raise ValueError('ICC Gamma 无效。')
            return lambda x: max(0., x)**gamma, 14
        values = tuple(v/65535 for v in struct.unpack_from(f'>{count}H', data, offset+12))
        return lambda x: interpolate(values, x), 12+count*2
    if kind != b'para':
        raise ValueError('ICC 包含不支持的曲线格式。')
    function = struct.unpack_from('>H', data, offset+8)[0]
    if function > 4:
        raise ValueError('ICC 参数曲线类型无效。')
    count = (1, 3, 4, 5, 7)[function]
    need(12+count*4)
    p = tuple(v/65536 for v in struct.unpack_from(f'>{count}i', data, offset+12))
    if p[0] <= 0 or (function and p[1] <= 0):
        raise ValueError('ICC 参数曲线数值无效。')

    def evaluate(x):
        g = p[0]
        if function == 0:
            return max(0., x)**g
        a, b = p[1:3]
        power = lambda: max(0., a*x+b)**g
        if function == 1:
            return power() if x >= -b/a else 0.
        if function == 2:
            return (power() if x >= -b/a else 0.) + p[3]
        c, d = p[3:5]
        if function == 3:
            return power() if x >= d else c*x
        e, f = p[5:7]
        return power()+e if x >= d else c*x+f
    return evaluate, 12+count*4


def encode_curve(evaluate):
    values = [round(max(0., min(1., evaluate(i/(SAMPLES-1))))*65535) for i in range(SAMPLES)]
    return b'curv' + bytes(4) + struct.pack('>I', SAMPLES) + struct.pack(f'>{SAMPLES}H', *values)


def compose_curve(evaluate, adjustment, channel, output):
    if output:
        return lambda x: adjustment.value(evaluate(x), channel)
    return lambda x: evaluate(adjustment.inverse(x, channel))


def edit_lut(data, adjustment, output):
    """Compose the device-side shaper; do not resample the multidimensional LUT."""
    kind = data[:4]
    if kind in (b'mft1', b'mft2'):
        if len(data) < 52 or data[8:10] != bytes((3, 3)) or data[10] < 2:
            raise ValueError('ICC RGB 查找表格式无效。')
        depth = 1 if kind == b'mft1' else 2
        ni, no = (256, 256) if depth == 1 else struct.unpack_from('>HH', data, 48)
        start = 48 if depth == 1 else 52
        end_input = start+3*ni*depth
        start_output = end_input+data[10]**3*3*depth
        if min(ni, no) < 2 or start_output+3*no*depth != len(data):
            raise ValueError('ICC 查找表长度无效。')
        result = bytearray(data)
        count, offset = (no, start_output) if output else (ni, start)
        code, scale = ('B', 255) if depth == 1 else ('H', 65535)
        for channel in range(3):
            pos = offset+channel*count*depth
            values = tuple(v/scale for v in struct.unpack_from(f'>{count}{code}', data, pos))
            evaluate = compose_curve(lambda x: interpolate(values, x), adjustment, channel, output)
            replacement = [round(max(0., min(1., evaluate(i/(count-1))))*scale) for i in range(count)]
            struct.pack_into(f'>{count}{code}', result, pos, *replacement)
        return bytes(result)
    if kind not in (b'mAB ', b'mBA ') or len(data) < 32 or data[8:10] != bytes((3, 3)):
        raise ValueError('这个 ICC 的转换表格式暂不支持编辑。')
    if kind != (b'mBA ' if output else b'mAB '):
        raise ValueError('ICC 转换表方向无效。')
    offsets = struct.unpack_from('>5I', data, 12)  # B, matrix, M, CLUT, A
    nonzero = sorted(set(o for o in offsets if o))
    if not offsets[0] or any(o < 32 or o % 4 or o >= len(data) for o in nonzero):
        raise ValueError('ICC 多阶段转换表无效。')
    # Device-side stage is A, otherwise M (next to matrix), otherwise B.
    selected = 4 if offsets[4] else 2 if offsets[2] else 0
    blocks = {}
    for i, offset in enumerate(offsets):
        if offset:
            next_offsets = [o for o in nonzero if o > offset]
            blocks[i] = data[offset:min(next_offsets) if next_offsets else len(data)]
    pos, replacement = 0, bytearray()
    for channel in range(3):
        evaluate, size = curve_reader(blocks[selected], pos)
        curve = encode_curve(compose_curve(evaluate, adjustment, channel, output))
        replacement.extend(curve + bytes(-len(curve) % 4))
        pos += size + (-size % 4)
    blocks[selected] = bytes(replacement)
    result = bytearray(data[:32])
    for i in range(5):
        if i in blocks:
            struct.pack_into('>I', result, 12+i*4, len(result))
            result.extend(blocks[i] + bytes(-len(blocks[i]) % 4))
    return bytes(result)


def description(name, version):
    unicode = name.encode('utf-16-be')
    if version == 4:
        return (b'mluc' + bytes(4) + struct.pack('>II', 1, 12) + b'enUS'
                + struct.pack('>II', len(unicode), 28) + unicode)
    ascii_name = name.encode('ascii', errors='replace') + b'\0'
    return (b'desc'+bytes(4)+struct.pack('>I', len(ascii_name))+ascii_name
            + struct.pack('>II', 0, len(unicode)//2+1)+unicode+b'\0\0'+bytes(70))


def pack_profile(header, tags):
    header = bytearray(header)
    header[24:36] = struct.pack('>6H', *datetime.now(timezone.utc).timetuple()[:6])
    header[84:100] = bytes(16)
    base = 132+12*len(tags)
    entries, payload, shared = bytearray(), bytearray(), {}
    for sig, data in tags.items():
        digest = hashlib.sha256(data).digest()
        if digest not in shared:
            shared[digest] = (base+len(payload), len(data))
            payload.extend(data + bytes(-len(data) % 4))
        entries.extend(struct.pack('>4sII', sig, *shared[digest]))
    result = header+struct.pack('>I', len(tags))+entries+payload
    struct.pack_into('>I', result, 0, len(result))
    if header[8] == 4:
        hash_input = bytearray(result)
        hash_input[44:48] = bytes(4)
        hash_input[64:68] = bytes(4)
        result[84:100] = hashlib.md5(hash_input).digest()
    return bytes(result)


def edited_profile(data, adjustment, name):
    tags = read_tags(data)
    if adjustment.active:
        changed = False
        for sig in list(tags):
            if sig[:3] in (b'A2B', b'B2A'):
                tags[sig] = edit_lut(tags[sig], adjustment, sig[:3] == b'B2A')
                changed = True
        trcs = (b'rTRC', b'gTRC', b'bTRC')
        if all(sig in tags for sig in trcs):
            for channel, sig in enumerate(trcs):
                evaluate, _ = curve_reader(tags[sig])
                tags[sig] = encode_curve(compose_curve(evaluate, adjustment, channel, False))
            changed = True
        if not changed or (not any(sig.startswith(b'B2A') for sig in tags)
                           and not all(sig in tags for sig in trcs)):
            raise ValueError('这个 ICC 缺少可编辑的 RGB 输出转换。')
        # Cached previews and PostScript conversions describe the old device mapping.
        for sig in (b'pre0', b'pre1', b'pre2', b'psd0', b'psd1', b'psd2', b'psd3', b'ps2s', b'ps2i'):
            tags.pop(sig, None)
    tags[b'desc'] = description(name, data[8])
    tags[b'qpet'] = b'text'+bytes(4)+json.dumps({
        'application': 'QuickPhotoPrint', 'base_sha256': hashlib.sha256(data).hexdigest(),
        'adjustment': asdict(adjustment), 'space': 'device RGB',
    }, ensure_ascii=True).encode('ascii')+b'\0'
    result = pack_profile(data[:128], tags)
    # The same engine used by the app must accept both directions and all intents.
    profile = ImageCms.getOpenProfile(BytesIO(result))
    srgb = ImageCms.createProfile('sRGB')
    for intent in range(4):
        ImageCms.buildTransform(srgb, profile, 'RGB', 'RGB', renderingIntent=intent)
        ImageCms.buildTransform(profile, srgb, 'RGB', 'RGB', renderingIntent=intent)
    return result


def save_adjusted_profile(profile, destination, adjustment):
    destination = Path(destination).expanduser().resolve()
    if profile != 'srgb' and Path(profile).expanduser().resolve() == destination:
        raise ValueError('请另选文件名，保留正在编辑的原始 ICC。')
    data = edited_profile(profile_bytes(profile), adjustment, destination.stem)
    # A failed export must not damage an existing target file.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix='.icc', delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
        os.replace(temp_path, destination)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return destination
