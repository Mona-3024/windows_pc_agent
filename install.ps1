# ===========================
# WIPE AGENT – WINDOWS INSTALLER
# ===========================

Write-Host "Installing Windows PC Wipe Agent..."

# --- 1. Check for admin privileges ---
If (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "Please run PowerShell as Administrator!"
    exit
}

# --- 2. Install Python if missing ---
if (-not (Get-Command python.exe -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Installing..."
    winget install -e --id Python.Python.3.12
}

# --- 3. Create working directory ---
$dir = "C:\pc_wipe_agent"
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir }

# --- 4. Download the pc_wipe_agent.py script ---
Invoke-WebRequest `
    -Uri "https://raw.githubusercontent.com/Mona-3024/windows_pc_agent/refs/heads/main/pc_wipe_agent.py" `
    -OutFile "$dir\pc_wipe_agent.py"

# --- 5. Create virtual environment ---
python -m venv "$dir\venv"
& "$dir\venv\Scripts\python.exe" -m pip install --upgrade pip
& "$dir\venv\Scripts\python.exe" -m pip install flask psutil

# --- 6. Download and install NSSM (to run as service) ---
Write-Host "Installing NSSM service manager..."
if (-not (Test-Path "C:\nssm\nssm.exe")) {
    New-Item -ItemType Directory -Path "C:\nssm" -Force
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "C:\nssm\nssm.zip"
    Expand-Archive "C:\nssm\nssm.zip" "C:\nssm" -Force
    Copy-Item "C:\nssm\*/win64/nssm.exe" "C:\nssm\nssm.exe" -Force
}

$nssm = "C:\nssm\nssm.exe"

# --- 7. Install pc_wipe_agent as a Windows service ---
& $nssm install pc_wipe_agent "$dir\venv\Scripts\python.exe" "$dir\pc_wipe_agent.py"
& $nssm set pc_wipe_agent Start SERVICE_AUTO_START
& $nssm set pc_wipe_agent AppRestartDelay 3000

# --- 8. Start the service ---
Start-Service pc_wipe_agent

Write-Host "===================================="
Write-Host " PC WIPE AGENT INSTALLED SUCCESSFULLY"
Write-Host " Service Name : pc_wipe_agent"
Write-Host " Runs at Boot : YES"
Write-Host " API Port     : 5050"
Write-Host "===================================="
