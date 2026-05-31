param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime = Join-Path $Root "data\runtime"
$PidFile = Join-Path $Runtime "qqbot.pid"

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

if ($ids.Count -eq 0) {
    Write-Host "No qqbot process found."
    exit 0
}

foreach ($id in $ids) {
    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        continue
    }
    Write-Host "Stopping qqbot process: PID=$id"
    if (-not $DryRun) {
        Stop-Process -Id $id -Force
    }
}

if ($DryRun) {
    Write-Host "Dry run complete. qqbot was not stopped."
    exit 0
}

if (Test-Path $PidFile) {
    Remove-Item -LiteralPath $PidFile -Force
}

Write-Host "qqbot stopped."
