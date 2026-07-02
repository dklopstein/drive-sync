# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (Test-Path "sync.pid") {
    $pidVal = Get-Content "sync.pid" -Raw
    $proc = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Sync process is RUNNING." -ForegroundColor Green
        Write-Host "PID: $pidVal"
        Write-Host "Start Time: $($proc.StartTime)"
    } else {
        Write-Host "Sync process is NOT running (stale sync.pid found)." -ForegroundColor Red
    }
} else {
    Write-Host "Sync process is NOT running." -ForegroundColor Red
}

if (Test-Path "sync.log") {
    Write-Host "`nLast 5 log entries:" -ForegroundColor Cyan
    Get-Content "sync.log" -Tail 5
}
