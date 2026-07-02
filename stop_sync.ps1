# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

if (Test-Path "sync.pid") {
    $pidVal = Get-Content "sync.pid" -Raw
    if (Get-Process -Id $pidVal -ErrorAction SilentlyContinue) {
        Write-Host "Stopping sync process with PID $pidVal..." -ForegroundColor Yellow
        Stop-Process -Id $pidVal -Force
        Write-Host "Sync process stopped." -ForegroundColor Green
    } else {
        Write-Host "Sync process with PID $pidVal was not running." -ForegroundColor Yellow
    }
    Remove-Item "sync.pid" -Force
} else {
    Write-Host "No active sync process found (sync.pid is missing)." -ForegroundColor Yellow
}
