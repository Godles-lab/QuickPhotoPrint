"""Explicit CI-only native Windows PDF driver check; never target a real printer."""
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from pypdf import PdfReader
from PySide6.QtGui import QPageSize
from PySide6.QtWidgets import QApplication
from windows_printing import WindowsPrinting


def main():
    assert sys.platform=='win32' and os.environ.get('CI')=='true'
    qt=QApplication([])
    backend=WindowsPrinting()
    # CI creates this uniquely named virtual queue with the Microsoft PDF driver.
    name='QuickPhotoPrint-Test-PDF'
    page=QPageSize(QPageSize.PageSizeId.A4)
    config=backend.prepare(name,page,210,297)
    again=backend.prepare(name,page,210,297,config.saved())
    assert again.geometry==config.geometry
    assert min(config.geometry.size_mm)>0
    with tempfile.TemporaryDirectory() as folder:
        output=Path(folder)/'native-driver-test.pdf'
        backend.print_page(config,Image.new('RGB',(420,594),'#a06040'),2,str(output))
        deadline=time.monotonic()+30
        while not output.exists() and time.monotonic()<deadline:time.sleep(.1)
        pdf=PdfReader(output)
        assert len(pdf.pages)==2
        for sheet in pdf.pages:
            assert abs(float(sheet.mediabox.width)*25.4/72-210)<.5
            assert abs(float(sheet.mediabox.height)*25.4/72-297)<.5
            assert len(sheet.images)>0
    print('Native Windows DEVMODE/GDI: two PDF pages, exact A4 size, image output, saved settings passed.')


if __name__=='__main__':main()
