# Build with: python -m PyInstaller --noconfirm PlanePlane.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root=Path(SPECPATH)
# Only assets used by the runtime; Blender sources aren't needed to play.
datas=[(str(path),str(path.parent.relative_to(root)))
       for path in (root/'assets').rglob('*')
       if path.is_file() and path.suffix.lower() in ('.png','.npz','.npy','.json')]
datas+=collect_data_files('tzdata')
hiddenimports=collect_submodules('websockets')+collect_submodules('glcontext')+['_moderngl']

a=Analysis([str(root/'desktop.py')],pathex=[str(root)],binaries=[],datas=datas,
           hiddenimports=hiddenimports,hookspath=[],hooksconfig={},runtime_hooks=[],
           excludes=['pytest','bpy','matplotlib','tkinter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='PlanePlane',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=False,
        disable_windowed_traceback=False,icon='NONE')
