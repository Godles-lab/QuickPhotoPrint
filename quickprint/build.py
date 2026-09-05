"""Run on each target OS; never bundle user data or development directories."""
from pathlib import Path
import importlib.metadata
import platform
import os
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
NAME='QuickPhotoPrint'
assets=ROOT/'build-assets'
assets.mkdir(exist_ok=True)
licenses=assets/'licenses'
licenses.mkdir(exist_ok=True)
shutil.copytree(ROOT/'licenses',licenses,dirs_exist_ok=True)
for name in ['PySide6','PySide6_Essentials','shiboken6','Pillow']:
    dist=importlib.metadata.distribution(name)
    for f in dist.files or []:
        if 'license' in str(f).lower() or 'copying' in str(f).lower():
            src=Path(dist.locate_file(f))
            if src.is_file():
                # Only distribution-supplied license files, never full environment.
                dest=licenses/name/Path(str(f)).name
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,dest)
from PySide6.QtCore import QLibraryInfo
from PyInstaller.building.makespec import main as make_spec
translations=assets/'qt-translations'
translations.mkdir(exist_ok=True)
for f in Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)).glob('qtbase_*.qm'):
    shutil.copy2(f,translations/f.name)
spec=Path(make_spec([str(ROOT/'app.py')],name=NAME,console=False,onefile=False,
    shorthand_manifest=None,specpath=str(assets),bundle_identifier='io.github.godleslab.quickphotoprint',
    datas=[(str(ROOT.parent/'Brother-T735DW-Kodak-Glossy.icc'),'profiles'),
           (str(licenses),'licenses'),(str(translations),'qt-translations'),(str(ROOT/'assets'),'assets'),
           (str(ROOT/'README.md'),'.'),(str(ROOT/'THIRD_PARTY.md'),'.')],
    excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtQml',
              'PySide6.QtQuick','tkinter','pytest']))
if sys.platform=='darwin':
    text=spec.read_text()
    assert 'app = BUNDLE(' in text
    text=text.replace('bundle_identifier=',"info_plist={'CFBundleAllowMixedLocalizations': True, 'CFBundleShortVersionString': '0.2.0'},\n    bundle_identifier=",1)
    spec.write_text(text)
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean',
                '--distpath',str(ROOT/'dist'),'--workpath',str(ROOT/'build'),str(spec)],check=True,cwd=ROOT)
if sys.platform=='darwin':
    import plistlib
    with (ROOT/'dist'/f'{NAME}.app'/'Contents'/'Info.plist').open('rb') as f:
        assert plistlib.load(f)['CFBundleAllowMixedLocalizations'] is True
# Launch the built executable, not the source interpreter, before releasing.
executable = (ROOT/'dist'/f'{NAME}.app'/'Contents'/'MacOS'/NAME if sys.platform=='darwin'
              else ROOT/'dist'/NAME/f'{NAME}.exe')
env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
subprocess.run([str(executable),'--smoke-test'],env=env,check=True,timeout=90)
release=ROOT/'release'; release.mkdir(exist_ok=True)
arch=platform.machine().lower()
if sys.platform=='darwin':
    archive=release/f'{NAME}-macOS-{arch}.zip'
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(ROOT/'dist'/f'{NAME}.app'),str(archive)],check=True)
else:
    archive=release/f'{NAME}-Windows-{arch}.zip'
    shutil.make_archive(str(archive.with_suffix('')),'zip',ROOT/'dist',NAME)
print(archive)
