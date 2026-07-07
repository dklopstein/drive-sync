# Get script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# =====================================================================
# CLEAN RESET ZONE: Kill any existing background sync processes
# =====================================================================
Write-Host "Initiating sync engine reset..." -ForegroundColor Cyan

# 1. Kill process listed in sync.pid if running
if (Test-Path "sync.pid") {
    $oldPid = Get-Content "sync.pid" -Raw
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        Write-Host "Stopping sync process with PID $oldPid from sync.pid..." -ForegroundColor Yellow
        Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    }
    Remove-Item "sync.pid" -Force
}

# 2. Kill all other running python/pythonw sync processes executing sync_drive.py
$currentPID = $PID
$oldProcesses = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%' AND CommandLine LIKE '%sync_drive%'"
foreach ($proc in $oldProcesses) {
    if ($proc.ProcessId -ne $currentPID) {
        Write-Host "Stopping frozen sync engine instance (PID: $($proc.ProcessId))" -ForegroundColor Yellow
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# Short pause to let the operating system release file locks
Start-Sleep -Seconds 2

# Ensure config.json and credentials.json exist
if (-not (Test-Path "config.json")) {
    Write-Host "Error: config.json not found! Please create it." -ForegroundColor Red
    exit
}
if (-not (Test-Path "credentials.json")) {
    Write-Host "Error: credentials.json not found! Please place your credentials.json from Google Cloud Console here." -ForegroundColor Red
    exit
}

# Ensure token.json exists, or run interactively first to authenticate
if (-not (Test-Path "token.json")) {
    Write-Host "token.json not found. Running interactive authentication flow first..." -ForegroundColor Cyan
    # Run interactively using standard python to get oauth token
    & ".\venv\Scripts\python.exe" sync_drive.py --check-auth
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Authentication failed. Background process not started." -ForegroundColor Red
        exit
    }
}

# Start the background sync process silently
Write-Host "Starting background sync process..." -ForegroundColor Green
Start-Process -FilePath ".\venv\Scripts\pythonw.exe" -ArgumentList "sync_drive.py" -WindowStyle Hidden -WorkingDirectory $scriptDir

# Wait a moment to allow the process to write sync.pid
Start-Sleep -Seconds 1.5

if (Test-Path "sync.pid") {
    $pidVal = Get-Content "sync.pid" -Raw
    Write-Host "Background sync started successfully with PID $pidVal." -ForegroundColor Green
} else {
    Write-Host "Failed to start background sync. Check sync.log for details." -ForegroundColor Red
}
