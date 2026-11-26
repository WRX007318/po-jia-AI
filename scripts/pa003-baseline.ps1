param(
    [string]$HomeDir = 'D:\PoJiaAI',
    [string]$OutputDir = ''
)
$ErrorActionPreference = 'Stop'
if (-not $OutputDir) { $OutputDir = Join-Path $HomeDir 'logs\pa003' }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$report = Join-Path $OutputDir ("baseline-" + $stamp + ".txt")
$rows = New-Object 'System.Collections.Generic.List[string]'
function Add-Text([string]$s) { $rows.Add($s); Write-Host $s }
function Add-Block($obj) { Add-Text ($obj | Out-String -Width 300) }
Add-Text ("Captured: " + (Get-Date -Format o))
Add-Text 'LOCAL RAW EVIDENCE: inspect and redact before publishing to GitHub.'
$os = Get-CimInstance Win32_OperatingSystem
$free = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$total = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
Add-Text ("RAM total GiB: $total; RAM available GiB: $free")
if ($free -lt 16) { Add-Text 'WARNING: available RAM below 16 GiB; close nonessential desktop apps manually. Continue stage 1.' }
Add-Text 'Top 5 processes in current desktop session by working set:'
$sid = (Get-Process -Id $PID).SessionId
Add-Block (Get-Process | Where-Object {$_.SessionId -eq $sid} | Sort-Object WorkingSet64 -Descending | Select-Object -First 5 Name,Id,@{n='WorkingSetMiB';e={[math]::Round($_.WorkingSet64 / 1MB,1)}} | Format-Table -AutoSize)
Add-Text 'NVIDIA GPU/driver (MiB):'
try {
    $smi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $smi) { throw 'nvidia-smi.exe not found' }
    $gpu = & $smi.Source --query-gpu=name,driver_version,memory.total,memory.used,memory.free --format=csv 2>&1
    $gpuExit = $LASTEXITCODE
    Add-Block $gpu
    Add-Text ("nvidia-smi exit: " + $gpuExit)
} catch { Add-Text ("GPU observation unavailable: " + $_.Exception.Message) }
Add-Text 'Actual llama-server process command lines:'
try {
    $servers = @(Get-CimInstance Win32_Process -Filter "Name = 'llama-server.exe'")
    if ($servers.Count -eq 0) { Add-Text 'No running llama-server process found.' }
    else { Add-Block ($servers | Select-Object ProcessId,ExecutablePath,CommandLine | Format-List) }
} catch { $servers = @(); Add-Text ("Process observation failed: " + $_.Exception.Message) }
$exe = Join-Path $HomeDir 'runtime\llama-server.exe'
if ($servers.Count -gt 0 -and $servers[0].ExecutablePath) { $exe = $servers[0].ExecutablePath }
Add-Text ("Binary for version/help: " + $exe)
if (Test-Path -LiteralPath $exe) {
    try {
        $v = & $exe --version 2>&1
        $versionExit = $LASTEXITCODE
        Add-Block $v
        Add-Text ("--version exit: " + $versionExit)
    } catch { Add-Text ("Version observation failed: " + $_.Exception.Message) }
    try {
        $helpFile = Join-Path $OutputDir ("server-help-" + $stamp + ".txt")
        & $exe --help 2>&1 | Out-File -FilePath $helpFile -Encoding utf8
        Add-Text ("--help exit: " + $LASTEXITCODE + "; saved: " + $helpFile)
    } catch { Add-Text ("Help observation failed: " + $_.Exception.Message) }
} else { Add-Text 'Binary not found; version/help not verified.' }
$rows | Out-File -FilePath $report -Encoding utf8
Write-Host ("Local raw baseline: " + $report)
