param(
    [Parameter(Mandatory=$true)][string]$ModelPath,
    [Parameter(Mandatory=$true)][ValidateSet('IQ3_S','IQ2_M')][string]$Quant,
    [int]$GpuLayers = 99,
    [int]$CpuMoe = 0,
    [int[]]$Contexts = @(2048,4096,8192),
    [int[]]$ThreadCounts = @(4,6),
    [string]$ServerExe = 'D:\PoJiaAI\runtime-cuda12-b12774\llama-server.exe',
    [string]$Mmproj = 'D:\PoJiaAI\models\inkling2mini\mmproj-Inkling-2-Mini-Uncensored-F16.gguf',
    [string]$OutputDir = 'D:\PoJiaAI\logs\pa003\matrix'
)
$ErrorActionPreference='Stop'
$RepoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python='C:\Users\Administrator\AppData\Local\Python\bin\python3.exe'
if(!(Test-Path -LiteralPath $ModelPath)){throw "Model file missing: $ModelPath"}
if(!(Test-Path -LiteralPath $ServerExe)){throw "CUDA llama-server missing: $ServerExe"}
if(!(Test-Path -LiteralPath $Python)){throw "Python missing: $Python"}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$summary=[System.Collections.Generic.List[object]]::new()
foreach($ctx in $Contexts){ foreach($threads in $ThreadCounts){
    $tag="$Quant-ngl$GpuLayers-moe$CpuMoe-ctx$ctx-t$threads"
    $port=59871
    $stdout=Join-Path $OutputDir "$tag-server.log"
    $stderr=Join-Path $OutputDir "$tag-server.err.log"
    $resourceLog=Join-Path $OutputDir "$tag-resources.csv"
    $sampler=$null
    'utc,free_ram_kib,gpu_memory_used_mib,gpu_memory_free_mib,gpu_utilization_pct' | Set-Content -LiteralPath $resourceLog -Encoding ascii
    $beforeRam=(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
    $beforeGpu=nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader
    $args=@('-m',$ModelPath,'--mmproj',$Mmproj,'--host','127.0.0.1','--port',"$port",'-ngl',"$GpuLayers",'-c',"$ctx",'-np','1','-t',"$threads",'-tb',"$threads",'-fa','on','-ctk','q8_0','-ctv','q8_0','--jinja','--reasoning','off','--reasoning-budget','64','--no-reasoning-preserve','--metrics')
    if($CpuMoe -gt 0){$args += @('--n-cpu-moe',"$CpuMoe")}
    $proc=Start-Process -FilePath $ServerExe -ArgumentList $args -WorkingDirectory (Split-Path $ServerExe) -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $ready=$false;$failure=$null
    try{
        $deadline=(Get-Date).AddMinutes(6)
        while((Get-Date) -lt $deadline -and !$proc.HasExited){
            try{$h=Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2;if($h.status -eq 'ok'){$ready=$true;break}}catch{}
            Start-Sleep -Seconds 2
        }
        if(!$ready){throw "server failed to become ready; exit=$($proc.ExitCode)"}
        $afterRam=(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
        $afterGpu=nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader
        $sampler=Start-Job -ArgumentList $resourceLog -ScriptBlock {
            param($path)
            while($true){
                $ram=(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
                $gpu=(nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader) -replace '\s*,\s*',','
                "$(Get-Date -Format o),$ram,$gpu" | Add-Content -LiteralPath $path -Encoding ascii
                Start-Sleep -Milliseconds 500
            }
        }
        $probeArgs=@('-m','tests.run_pa003_probes','--probe','all','--backend','CUDA','--build','b12774','--quant',$Quant,'--gpu-layers',"$GpuLayers",'--cpu-moe',"$CpuMoe",'--context',"$ctx",'--threads',"$threads",'--threads-batch',"$threads",'--kv-cache','q8_0','--flash-attention','enabled','--mmproj-offload','yes','--reasoning-budget-tokens','64','--server-command',"CUDA b12774; -ngl $GpuLayers; --n-cpu-moe $CpuMoe; -c $ctx; -t $threads",'--output-dir',$OutputDir)
        & $Python @probeArgs
        $probeExit=$LASTEXITCODE
        Stop-Job $sampler;Remove-Job $sampler
        $summary.Add([pscustomobject]@{profile=$tag;status=if($probeExit -eq 0){'probes_all_pass'}else{'probe_gate_failure'};probe_exit=$probeExit;ram_free_before_kib=$beforeRam;ram_free_ready_kib=$afterRam;gpu_before=$beforeGpu;gpu_ready=$afterGpu;server_pid=$proc.Id;stdout=$stdout;stderr=$stderr;resource_samples=$resourceLog})
    }catch{
        $failure=$_.Exception.Message
        $summary.Add([pscustomobject]@{profile=$tag;status='startup_or_probe_error';error=$failure;ram_free_before_kib=$beforeRam;gpu_before=$beforeGpu;server_pid=$proc.Id;stdout=$stdout;stderr=$stderr})
    }finally{
        if($sampler){Stop-Job $sampler -ErrorAction SilentlyContinue;Remove-Job $sampler -Force -ErrorAction SilentlyContinue}
        if(!$proc.HasExited){Stop-Process -Id $proc.Id -ErrorAction SilentlyContinue;Wait-Process -Id $proc.Id -Timeout 20 -ErrorAction SilentlyContinue}
        try{Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$port/shutdown" -TimeoutSec 2|Out-Null}catch{}
        Start-Sleep -Seconds 3
    }
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDir 'matrix-progress.json') -Encoding utf8
} }
$summary | ConvertTo-Json -Depth 8
