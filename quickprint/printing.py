"""Driver-native media selection and Qt system-dialog localization."""
from pathlib import Path
from PySide6.QtCore import QLocale, QTranslator, QLibraryInfo, QSizeF, QMarginsF
from PySide6.QtGui import QPageSize, QPageLayout


def borderless_page(page):
    text=(page.key()+' '+page.name()).casefold()
    return any(word in text for word in ('fullbleed','borderless','无边','無邊','フチなし','縁なし'))


def match_page(pages, width, height, borderless=False):
    """Return original driver QPageSize (including vendor paper key), not a copy by mm."""
    target=sorted((width,height))
    candidates=[]
    for page in pages:
        mm=page.size(QPageSize.Unit.Millimeter)
        dims=sorted((mm.width(),mm.height()))
        error=max(abs(dims[i]-target[i]) for i in (0,1))
        if error<=.8:
            candidates.append((borderless_page(page)!=borderless,error,page))
    if candidates:
        return min(candidates,key=lambda c:(c[0],c[1]))[2]
    return None


def configure_paper(printer, info, width, height, borderless=False):
    page=match_page(info.supportedPageSizes(),width,height,borderless)
    if page is None:
        if not info.supportsCustomPageSizes():
            raise ValueError('这台打印机没有匹配的纸张，也不支持自定义尺寸，请选择其他尺寸。')
        page=QPageSize(QSizeF(min(width,height),max(width,height)),QPageSize.Unit.Millimeter,
                       f'{width:g} × {height:g} mm',QPageSize.SizeMatchPolicy.ExactMatch)
    # Some driver-native media have width > height; preserve their native orientation.
    mm=page.size(QPageSize.Unit.Millimeter)
    swapped=(width>height)!=(mm.width()>mm.height())
    orientation=QPageLayout.Orientation.Landscape if swapped else QPageLayout.Orientation.Portrait
    if not printer.setPageSize(page):
        raise ValueError('打印驱动未接受这个纸张尺寸，请选择驱动支持的相纸。')
    # Keep driver-provided minimum margins; constructing a zero-margin layout can
    # be rejected even when the paper itself is supported (macOS Brother driver).
    layout=printer.pageLayout()
    layout.setOrientation(orientation)
    layout.setMode(QPageLayout.Mode.FullPageMode)
    if not printer.setPageLayout(layout):
        raise ValueError('打印驱动未接受纸张方向，请调整后重试。')
    printer.setFullPage(True)
    actual=printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter)
    if abs(actual.width()-width)>1 or abs(actual.height()-height)>1:
        raise ValueError('驱动没有保留所选纸张尺寸，本次未打开打印窗口。')
    return page


def install_system_translations(app, base, locale=None):
    locale=locale or QLocale.system()
    folders=[Path(base)/'qt-translations',Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))]
    installed=[]
    for folder in folders:
        translator=QTranslator(app)
        if translator.load(locale,'qtbase','_',str(folder)):
            app.installTranslator(translator)
            installed.append(translator)
            break
    # Hold references for the full QApplication lifetime.
    app._system_translators=installed
    return installed
