$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $repo 'dist'
$desktopDist = Join-Path $distRoot 'PoJiaAI'
$build = Join-Path $repo 'build\pyinstaller'
$venv = Join-Path $repo '.pa006-build-env'
$python = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python)) {
  & py -3.11 -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw '无法创建 Python 3.11 打包环境。' }
}

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw '无法更新隔离打包环境中的 pip。' }
& $python -m pip install -r (Join-Path $repo 'requirements-windows.txt') -r (Join-Path $repo 'requirements-build-windows.txt')
if ($LASTEXITCODE -ne 0) { throw '安装 PyInstaller 或桌面 Agent 依赖失败。' }

New-Item -ItemType Directory -Path $desktopDist -Force | Out-Null
New-Item -ItemType Directory -Path $build -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $build 'specs') -Force | Out-Null

& $python -m PyInstaller --noconfirm --clean --windowed --onedir `
  --name PoJiaAI --distpath $distRoot --specpath (Join-Path $build 'specs') --workpath (Join-Path $build 'desktop') `
  --paths (Join-Path $repo 'app') (Join-Path $repo 'launch.pyw')
if ($LASTEXITCODE -ne 0) { throw '破甲 AI 桌面程序打包失败。' }

$workerDist = Join-Path $desktopDist 'PoJiaAI-Worker'
& $python -m PyInstaller --noconfirm --clean --windowed --onedir `
  --name PoJiaAI-Worker --distpath $desktopDist --specpath (Join-Path $build 'specs') --workpath (Join-Path $build 'worker') `
  --paths (Join-Path $repo 'app') (Join-Path $repo 'app\vision_worker.py')
if ($LASTEXITCODE -ne 0) { throw '独立视觉 Worker 打包失败。' }

$desktopExe = Join-Path $desktopDist 'PoJiaAI.exe'
$workerExe = Join-Path $workerDist 'PoJiaAI-Worker.exe'
if (-not (Test-Path -LiteralPath $desktopExe) -or -not (Test-Path -LiteralPath $workerExe)) {
  throw '打包产物缺失桌面程序或独立视觉 Worker。'
}

Write-Output "Desktop executable: $desktopExe"
Write-Output "Independent worker: $workerExe"
Write-Output 'Models and llama.cpp runtime remain external under D:\PoJiaAI; this package does not contain model weights.'
