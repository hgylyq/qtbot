param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $Root "data\runtime"
$PidFile = Join-Path $Runtime "qqbot.pid"
$OutLog = Join-Path $Runtime "qqbot.out.log"
$ErrLog = Join-Path $Runtime "qqbot.err.log"

function Stop-BotProcess {
    $ids = New-Object System.Collections.Generic.HashSet[int]

    if (Test-Path $PidFile) {
        $raw = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        $pidValue = 0
        if ([int]::TryParse($raw, [ref]$pidValue)) {
            [void]$ids.Add($pidValue)
        }
    }

    try {
        $escapedRoot = [regex]::Escape($Root)
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
            Where-Object {
                $_.CommandLine -match "\s-m\s+qqbot(\s|$)" -and
                ($_.CommandLine -match $escapedRoot -or $_.ExecutablePath -like "*Python*")
            } |
            ForEach-Object { [void]$ids.Add([int]$_.ProcessId) }
    } catch {
        Write-Warning "Could not inspect Python command lines: $($_.Exception.Message)"
    }

    foreach ($id in $ids) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($null -eq $proc) {
            continue
        }
        Write-Host "Stopping existing qqbot process: PID=$id"
        if (-not $DryRun) {
            Stop-Process -Id $id -Force
        }
    }
}

function Start-BotProcess {
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    $python = (Get-Command python).Source
    Write-Host "Starting qqbot with $python"
    if ($DryRun) {
        return
    }

    $proc = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "qqbot") `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog

    Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII
    Start-Sleep -Seconds 3
    if ($proc.HasExited) {
        Write-Error "qqbot exited immediately with code $($proc.ExitCode). See $ErrLog"
    }

    Write-Host "qqbot restarted. PID=$($proc.Id)"
    Write-Host "stdout: $OutLog"
    Write-Host "stderr: $ErrLog"
}

Set-Location $Root
Stop-BotProcess
Start-BotProcess
