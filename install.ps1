# ===========================
# SECURE WIPE AGENT – WINDOWS INSTALLER v2.0
# ===========================
Write-Host "Installing Secure Wipe Agent..." -ForegroundColor Cyan

# --- 1. Require Administrator ---
If (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "ERROR: This script must be run as Administrator!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# --- 2. Define paths ---
$InstallDir = "C:\ProgramData\SecureWipeAgent"  # Hidden & protected location
$ScriptPath = "$InstallDir\pc_wipe_agent.py"
$VenvPath   = "$InstallDir\venv"
$NssmPath   = "C:\nssm\nssm.exe"
$ServiceName = "SecureWipeAgent"

# --- 3. Install Python if missing ---
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Python 3.12 via winget..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
}

# --- 4. Create secure install directory ---
if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
# Hide the folder
(attrib +h $InstallDir) | Out-Null

# --- 5. Download latest agent script ---
Write-Host "Downloading latest pc_wipe_agent.py..."
Invoke-WebRequest `
    -Uri "https://raw.githubusercontent.com/Mona-3024/windows_pc_agent/refs/heads/main/pc_wipe_agent.py" `
    -OutFile $ScriptPath -UseBasicParsing

# --- 6. Create virtual environment ---
Write-Host "Setting up Python virtual environment..."
python -m venv $VenvPath
& "$VenvPath\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$VenvPath\Scripts\pip.exe" install --quiet flask cryptography

# --- 7. Install NSSM (Non-Sucking Service Manager) ---
if (-not (Test-Path $NssmPath)) {
    Write-Host "Downloading NSSM..."
    New-Item -ItemType Directory -Path "C:\nssm" -Force | Out-Null
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "C:\temp_nssm.zip" -UseBasicParsing
    Expand-Archive "C:\temp_nssm.zip" "C:\nssm" -Force
    Move-Item "C:\nssm\nssm-2.24\win64\nssm.exe" $NssmPath -Force
    Remove-Item "C:\temp_nssm.zip", "C:\nssm\nssm-2.24" -Recurse -Force
}

# --- 8. Remove old service if exists ---
& $NssmPath remove $ServiceName confirm 2>$null

# --- 9. Install as hidden auto-start service ---
Write-Host "Registering service: $ServiceName"
& $NssmPath install $ServiceName "$VenvPath\Scripts\python.exe" $ScriptPath
& $NssmPath set $ServiceName AppDirectory $InstallDir
& $NssmPath set $ServiceName DisplayName "Windows Security Wipe Service"
& $NssmPath set $ServiceName Description "Background agent for secure data sanitization and audit certificates."
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName AppRestartDelay 5000
& $NssmPath set $ServiceName AppStdout "$InstallDir\service.log"
& $NssmPath set $ServiceName AppStderr "$InstallDir\error.log"
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 1048576  # 1MB

# --- 10. Start service ---
Start-Service $ServiceName

# --- 11. Final status ---
Start-Sleep -Seconds 4
$svc = Get-Service $ServiceName -ErrorAction SilentlyContinue

Write-Host "========================================" -ForegroundColor Green
Write-Host " SECURE WIPE AGENT INSTALLED SUCCESSFULLY" -ForegroundColor Green
Write-Host " Service Name   : $ServiceName" 
Write-Host " Status         : $($svc.Status)" 
Write-Host " Runs at Boot   : YES"
Write-Host " Hidden Folder  : $InstallDir"
Write-Host " API Endpoint   : http://$(hostname):5055/"
Write-Host " Test command   : curl http://localhost:5055/?key=admin"
Write-Host "========================================" -ForegroundColor Green

# Optional: Open firewall port (uncomment if needed)
# New-NetFirewallRule -DisplayName "Secure Wipe Agent" -Direction Inbound -Protocol TCP -LocalPort 5055 -Action Allow

Read-Host "Press Enter to exit"
