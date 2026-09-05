"""Run on each target OS; never bundle user data or development directories."""
from pathlib import Path
import importlib.metadata
import platform
import os
import shutil
import subprocess
import sys
import sysconfig
import zipfile

ROOT=Path(__file__).resolve().parent
NAME='QuickPhotoPrint'
LEGACY_NAME='QuickPhotoPrintLocal'
assets=ROOT/'build-assets'
assets.mkdir(exist_ok=True)
for legacy in (ROOT/'dist'/f'{LEGACY_NAME}.app', ROOT/'dist'/LEGACY_NAME,
               ROOT/'build'/LEGACY_NAME, assets/f'{LEGACY_NAME}.spec'):
    if legacy.is_dir(): shutil.rmtree(legacy)
    elif legacy.exists(): legacy.unlink()
release=ROOT/'release'; release.mkdir(exist_ok=True)
for legacy in (release/f'{LEGACY_NAME}.app', release/LEGACY_NAME):
    if legacy.is_dir(): shutil.rmtree(legacy)
for legacy in release.glob(f'{LEGACY_NAME}-*.zip'):
    legacy.unlink()
# Derive each platform's icon from the shared transparent PNG.
from PIL import Image
icon=assets/('app-icon.icns' if sys.platform=='darwin' else 'app-icon.ico')
with Image.open(ROOT/'assets'/'app-icon.png') as source:
    artwork=source.convert('RGBA')
    if sys.platform=='darwin':
        artwork.resize((1024,1024),Image.Resampling.LANCZOS).save(icon,format='ICNS')
    else:
        artwork.save(icon,format='ICO',sizes=[(n,n) for n in (16,24,32,48,64,128,256)])
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
    icon_file=[str(icon)],
    shorthand_manifest=None,specpath=str(assets),bundle_identifier='io.github.godleslab.quickphotoprint',
    datas=[(str(ROOT.parent/'Brother-T735DW-Kodak-Glossy.icc'),'profiles'),
           (str(licenses),'licenses'),(str(translations),'qt-translations'),(str(ROOT/'assets'),'assets'),
           (str(ROOT/'README.md'),'.'),(str(ROOT/'THIRD_PARTY.md'),'.')],
    excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtQml',
              'PySide6.QtQuick','tkinter','pytest']))
if sys.platform=='darwin':
    text=spec.read_text()
    assert 'app = BUNDLE(' in text
    # AppKit save panels need an explicit bundle language declaration, even
    # when Qt translations are stored in .qm files rather than .lproj folders.
    bundle_info={'CFBundleAllowMixedLocalizations':True,
                 'CFBundleDevelopmentRegion':'zh-Hans',
                 'CFBundleLocalizations':['zh-Hans','zh-Hant','en'],
                 'CFBundleName':NAME,'CFBundleDisplayName':NAME,
                 'CFBundleShortVersionString':'0.2.12'}
    text=text.replace('bundle_identifier=',f'info_plist={bundle_info!r},\n    bundle_identifier=',1)
    spec.write_text(text)
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean',
                '--distpath',str(ROOT/'dist'),'--workpath',str(ROOT/'build'),str(spec)],check=True,cwd=ROOT)
if sys.platform=='darwin':
    import plistlib
    with (ROOT/'dist'/f'{NAME}.app'/'Contents'/'Info.plist').open('rb') as f:
        info=plistlib.load(f)
        assert info['CFBundleAllowMixedLocalizations'] is True
        assert info['CFBundleDevelopmentRegion']=='zh-Hans'
        assert info['CFBundleLocalizations']==['zh-Hans','zh-Hant','en']
        assert info['CFBundleName']==info['CFBundleDisplayName']==NAME
# Launch the built executable, not the source interpreter, before releasing.
executable = (ROOT/'dist'/f'{NAME}.app'/'Contents'/'MacOS'/NAME if sys.platform=='darwin'
              else ROOT/'dist'/NAME/f'{NAME}.exe')
env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
subprocess.run([str(executable),'--smoke-test'],env=env,check=True,timeout=90)
arch=platform.machine().lower()
if sys.platform=='win32':
    # An x64 Python on Windows ARM reports platform.machine() == ARM64.
    # Name the package for its Python/EXE target, not the host CPU.
    arch={'win-amd64':'x64','win-arm64':'arm64','win32':'x86'}[sysconfig.get_platform()]
if sys.platform=='darwin':
    archive=release/f'{NAME}-macOS-{arch}.zip'
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(ROOT/'dist'/f'{NAME}.app'),str(archive)],check=True)
else:
    archive=release/f'{NAME}-Windows-{arch}.zip'
    shutil.make_archive(str(archive.with_suffix('')),'zip',ROOT/'dist',NAME)
print(archive)
