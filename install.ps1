# =================================================
# SECURE WIPE AGENT - BULLETPROOF INSTALLER v3.1
# FIXES: Forces TLS 1.2 for GitHub downloads
# =================================================
$ErrorActionPreference = "Stop"

# --- CRITICAL FIX: FORCE TLS 1.2 FOR GITHUB ---
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# ----------------------------------------------

$InstallDir    = "C:\ProgramData\SecureWipeAgent"
$ServiceName   = "SecureWipeAgent"
# Switched to raw.githubusercontent to avoid 302 Redirect issues
$ScriptUrl     = "https://raw.githubusercontent.com/Mona-3024/windows_pc_agent/main/pc_wipe_agent.py"
$NssmUrl       = "https://raw.githubusercontent.com/Mona-3024/windows_pc_agent/main/nssm.exe"

Write-Host "`nSECURE WIPE AGENT - CLEAN REINSTALL (TLS 1.2 FIXED)" -ForegroundColor Cyan
Write-Host "====================================================`n" -ForegroundColor Cyan

# === STEP 1: KILL EVERYTHING BRUTALLY ===
Write-Host "[1/6] Killing all Python processes from $InstallDir..." -ForegroundColor Yellow
Get-Process -Name python*, py -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "*SecureWipeAgent*"
} | ForEach-Object {
    Write-Host "    Killing PID $($_.Id) - $($_.Path)"
    Stop-Process $_ -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

# === STEP 2: STOP & DELETE SERVICE (even if locked) ===
Write-Host "[2/6] Removing Windows service..." -ForegroundColor Yellow
Stop-Service $ServiceName -Force -ErrorAction SilentlyContinue
sc.exe delete $ServiceName 2>$null | Out-Null
Start-Sleep -Seconds 2

# === STEP 3: NUCLEAR DIRECTORY REMOVAL (handles locked files) ===
Write-Host "[3/6] Removing old installation (nuclear mode)..." -ForegroundColor Yellow
if (Test-Path $InstallDir) {
    # Method 1: Take ownership + full control
    takeown /F "$InstallDir" /R /D Y >$null 2>&1
    icacls "$InstallDir" /grant Administrators:F /T /C /Q >$null 2>&1

    # Method 2: Remove all attributes
    attrib -r -a -s -h "$InstallDir\*.*" /S /D >$null 2>&1

    # Method 3: Final delete with cmd (bypasses PowerShell locks)
    cmd /c "rd /s /q `"$InstallDir`" 2>nul"
    if (Test-Path $InstallDir) { cmd /c "rmdir /s /q `"$InstallDir`" 2>nul" }
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue }
}

# Wait for filesystem to catch up
Start-Sleep -Seconds 4

# === STEP 4: Fresh install ===
Write-Host "[4/6] Creating fresh directory..." -ForegroundColor Green
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
attrib +h $InstallDir  # hide it

Write-Host "[5/6] Downloading latest agent..." -ForegroundColor Green
try {
    Invoke-WebRequest -Uri $ScriptUrl -OutFile "$InstallDir\pc_wipe_agent.py" -UseBasicParsing
} catch {
    Write-Error "Failed to download agent script. Check internet or URL."
    exit 1
}

Write-Host "[6/6] Setting up Python venv + dependencies..." -ForegroundColor Green
& python -m venv "$InstallDir\venv" --clear
& "$InstallDir\venv\Scripts\pip.exe" install --quiet --upgrade pip
& "$InstallDir\venv\Scripts\pip.exe" install --quiet flask cryptography

# === STEP 5: Install as clean auto-start service using NSSM (best method) ===
$NssmPath = "$InstallDir\nssm.exe"
Write-Host "Installing NSSM service manager..." -ForegroundColor Green

try {
    # Using the direct raw link which is more reliable
    Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmPath -UseBasicParsing
} catch {
    Write-Error "Failed to download NSSM. The TLS handshake failed or the file is missing."
    exit 1
}

if (-not (Test-Path $NssmPath)) {
    Write-Error "NSSM download failed silently. File not found."
    exit 1
}

& $NssmPath install $ServiceName `"$InstallDir\venv\Scripts\python.exe`" `"$InstallDir\pc_wipe_agent.py`"
& $NssmPath set $ServiceName DisplayName "Windows Security Agent"
& $NssmPath set $ServiceName Description "Secure data sanitization service"
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName AppDirectory $InstallDir
& $NssmPath set $ServiceName AppStdout "$InstallDir\service.log"
& $NssmPath set $ServiceName AppStderr "$InstallDir\error.log"
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 1048576

Start-Service $ServiceName

# === DONE ===
Write-Host "`nSUCCESS! Agent is now running silently" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Service: $ServiceName"
Write-Host " Location: $InstallDir"
Write-Host " API: http://$(hostname):5055/"
Write-Host " Test: curl http://localhost:5055/?key=admin"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Reboot not required. Agent survives reboot." -ForegroundColor Gray
