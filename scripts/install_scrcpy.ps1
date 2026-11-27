param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\scrcpy')
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$archive = Join-Path $repoRoot 'tools\scrcpy\windows-x64\scrcpy-win64-v5.0.1.zip'
$panelSource = Join-Path $repoRoot 'tools\scrcpy\panel\scrcpy-panel.ps1'
$versionDirectory = Join-Path $InstallRoot 'scrcpy-win64-v5.0.1'
$scrcpyExe = Join-Path $versionDirectory 'scrcpy.exe'
$panelTarget = Join-Path $versionDirectory 'scrcpy-panel.ps1'

if (-not (Test-Path -LiteralPath $archive)) {
    throw "scrcpy archive not found: $archive"
}

New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $scrcpyExe)) {
    Expand-Archive -LiteralPath $archive -DestinationPath $versionDirectory -Force
}

if (-not (Test-Path -LiteralPath $scrcpyExe)) {
    throw "scrcpy.exe was not found after extraction: $scrcpyExe"
}
if (-not (Test-Path -LiteralPath $panelSource)) {
    throw "scrcpy panel not found: $panelSource"
}
Copy-Item -LiteralPath $panelSource -Destination $panelTarget -Force

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$pathEntries = @($userPath -split ';' | Where-Object { $_ })
if ($pathEntries -notcontains $versionDirectory) {
    $newUserPath = (@($pathEntries) + $versionDirectory) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'scrcpy.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $scrcpyExe
$shortcut.WorkingDirectory = $versionDirectory
$shortcut.Description = 'Android screen mirroring with scrcpy'
$shortcut.Save()

$panelShortcutPath = Join-Path $desktop 'scrcpy 功能面板.lnk'
$panelShortcut = $shell.CreateShortcut($panelShortcutPath)
$panelShortcut.TargetPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$panelShortcut.Arguments = "-NoProfile -STA -ExecutionPolicy Bypass -File `"$panelTarget`""
$panelShortcut.WorkingDirectory = $versionDirectory
$panelShortcut.IconLocation = "$scrcpyExe,0"
$panelShortcut.Description = 'scrcpy Android screen mirroring control panel'
$panelShortcut.Save()

Write-Host "Installed scrcpy to: $versionDirectory"
Write-Host "Desktop shortcut: $shortcutPath"
Write-Host "Control panel shortcut: $panelShortcutPath"
Write-Host 'Open a new PowerShell window to run scrcpy from PATH.'
