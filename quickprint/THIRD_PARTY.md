# Third-party components

- PySide6 / Qt 6 / Shiboken: LGPL-3.0 / GPL and component-specific licenses. Dynamically linked libraries are distributed in the application bundle; recipients may replace them with compatible builds and debug modifications as permitted by the applicable licenses. https://www.qt.io/licensing/open-source-lgpl-obligations · https://code.qt.io/cgit/pyside/pyside-setup.git/ · https://code.qt.io/cgit/qt/qtbase.git/
- Pillow / Little CMS: HPND / MIT and bundled library licenses. https://github.com/python-pillow/Pillow · https://github.com/mm2/Little-CMS
- Python: PSF license. https://docs.python.org/3/license.html
- PyInstaller bootloader: GPL with distribution exception. https://pyinstaller.org/en/stable/license.html

Distribution license texts are copied from installed packages into the bundled `licenses` directory during build. Application source is available in this repository. The application bundles no photographs.

The included Brother ICC is a personal compensation profile derived using Apple Generic RGB Profile; see the repository root README and retained ICC copyright metadata. The application source license does not relicense that profile or any third-party components.
