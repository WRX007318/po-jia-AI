# Windows package

Run `packaging/build_windows.ps1` from PowerShell. It creates an isolated Python 3.11 build environment, installs the pinned application dependency plus PyInstaller, and emits an onedir distribution at `dist/PoJiaAI/`.

The distribution contains `PoJiaAI.exe` and a separately bundled `PoJiaAI-Worker/PoJiaAI-Worker.exe`. Model weights, mmproj, and llama.cpp runtime stay under `D:\PoJiaAI`; the package intentionally excludes model weights. The desktop program fails visibly if the worker executable is missing.

After copying the complete `dist/PoJiaAI/` folder to its install location, run `install_desktop_shortcut.ps1` from the repository root to make the desktop shortcut target the packaged executable. If no package exists, the script falls back to `launch.pyw` through `pythonw.exe`.

Packaging is not deployment acceptance. Before distribution, verify the EXE on the target machine, including model auto-start, worker launch, stop/restart, data recovery, and desktop interaction.
