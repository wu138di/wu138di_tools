"""Build the portable Windows executable with the current Python interpreter."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT
if not (ROOT / 'assets/ffmpeg.exe').is_file():
    import shutil
    import imageio_ffmpeg
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), ROOT / 'assets/ffmpeg.exe')
command = [
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
    '--name', 'wu138di X GIF下载器 v1.0', '--icon', str(ROOT / 'assets/app.ico'),
    '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build-cache'),
    '--specpath', str(ROOT / 'build-cache'),
    '--version-file', str(ROOT / 'version.txt'),
    '--add-data', str(ROOT / 'ui') + ':ui',
    '--add-data', str(ROOT / 'licenses') + ':licenses',
    '--add-data', str(ROOT / 'assets/app.ico') + ':assets',
    '--add-binary', str(ROOT / 'assets/ffmpeg.exe') + ':assets',
    '--hidden-import', 'webview.platforms.winforms',
    '--hidden-import', 'webview.platforms.edgechromium',
]
for excluded in ['PySide6', 'PyQt6', 'PyQt5', 'PySide2', 'qtpy', 'tkinter', 'cefpython3',
                 'gi', 'gtk', 'wx', 'imageio_ffmpeg', 'numpy', 'PIL', 'matplotlib', 'pandas',
                 'scipy', 'IPython', 'jupyter', 'pytest', 'setuptools', 'torch']:
    command.extend(['--exclude-module', excluded])
command.append(str(ROOT / 'main.py'))
print(subprocess.list2cmdline(command), flush=True)
subprocess.run(command, cwd=ROOT, check=True)



