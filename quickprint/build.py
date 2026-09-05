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
cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir',
     '--name',NAME,'--distpath',str(ROOT/'dist'),'--workpath',str(ROOT/'build'),
     '--specpath',str(assets),'--add-data',f'{ROOT.parent / "Brother-T735DW-Kodak-Glossy.icc"}:profiles',
     '--add-data',f'{licenses}:licenses',
     '--add-data',f'{ROOT / "README.md"}:.',
     '--add-data',f'{ROOT / "THIRD_PARTY.md"}:.',
     '--exclude-module','PySide6.QtWebEngineCore','--exclude-module','PySide6.QtWebEngineWidgets',
     '--exclude-module','PySide6.QtQml','--exclude-module','PySide6.QtQuick',
     '--exclude-module','tkinter','--exclude-module','pytest']
if sys.platform=='darwin':
    cmd += ['--osx-bundle-identifier','io.github.godleslab.quickphotoprint']
cmd.append(str(ROOT/'app.py'))
subprocess.run(cmd,check=True,cwd=ROOT)
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
