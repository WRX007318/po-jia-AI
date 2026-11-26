$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'C:\Users\Administrator\AppData\Local\Python\pythoncore-3.15-64\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) {
  $python = Join-Path (Split-Path (Get-Command python.exe).Source -Parent) 'pythonw.exe'
}
if (-not (Test-Path -LiteralPath $python)) { throw '找不到 pythonw.exe。请安装支持 Tk 的 Python 3.11+。' }
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop '破甲 AI.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $python
$shortcut.Arguments = "`"$(Join-Path $repo 'launch.pyw')`""
$shortcut.WorkingDirectory = $repo
$shortcut.Description = '破甲 AI 本地工作台'
$shortcut.Save()
Write-Output "快捷方式已创建：$shortcutPath"
