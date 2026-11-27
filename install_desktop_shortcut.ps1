$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$packagedExe = Join-Path $repo 'dist\PoJiaAI\PoJiaAI.exe'
$python = $null
if (-not (Test-Path -LiteralPath $packagedExe)) {
  $python = 'C:\Users\Administrator\AppData\Local\Python\pythoncore-3.15-64\pythonw.exe'
  if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path (Split-Path (Get-Command python.exe).Source -Parent) 'pythonw.exe'
  }
  if (-not (Test-Path -LiteralPath $python)) { throw '找不到打包版破甲 AI，也找不到 pythonw.exe。请先构建 EXE 或安装支持 Tk 的 Python。' }
}
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop '破甲 AI.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = if (Test-Path -LiteralPath $packagedExe) { $packagedExe } else { $python }
$shortcut.Arguments = if (Test-Path -LiteralPath $packagedExe) { '' } else { "`"$(Join-Path $repo 'launch.pyw')`"" }
$shortcut.WorkingDirectory = if (Test-Path -LiteralPath $packagedExe) { Split-Path $packagedExe -Parent } else { $repo }
$shortcut.Description = '破甲 AI 本地工作台'
$shortcut.Save()
Write-Output "快捷方式已创建：$shortcutPath"
