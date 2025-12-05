# =================================================
# SECURE WIPE AGENT - BULLETPROOF INSTALLER v3.2
# FIXES: Downloads NSSM from official source
# =================================================
$ErrorActionPreference = "Stop"

# --- CRITICAL FIX: FORCE TLS 1.2 FOR GITHUB ---
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# ----------------------------------------------

$InstallDir    = "C:\ProgramData\SecureWipeAgent"
$ServiceName   = "SecureWipeAgent"
$ScriptUrl     = "https://raw.githubusercontent.com/Mona-3024/windows_pc_agent/main/pc_wipe_agent.py"
# Using official NSSM download from nssm.cc (more reliable)
$NssmUrl       = "https://nssm.cc/release/nssm-2.24.zip"

Write-Host "`nSECURE WIPE AGENT - CLEAN REINSTALL (NSSM FIXED)" -ForegroundColor Cyan
Write-Host "===================================================`n" -ForegroundColor Cyan

# === STEP 1: KILL EVERYTHING BRUTALLY ===
Write-Host "[1/7] Killing all Python processes from $InstallDir..." -ForegroundColor Yellow
Get-Process -Name python*, py -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "*SecureWipeAgent*"
} | ForEach-Object {
    Write-Host "    Killing PID $($_.Id) - $($_.Path)"
    Stop-Process $_ -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

# === STEP 2: STOP & DELETE SERVICE (even if locked) ===
Write-Host "[2/7] Removing Windows service..." -ForegroundColor Yellow
Stop-Service $ServiceName -Force -ErrorAction SilentlyContinue
sc.exe delete $ServiceName 2>$null | Out-Null
Start-Sleep -Seconds 2

# === STEP 3: NUCLEAR DIRECTORY REMOVAL (handles locked files) ===
Write-Host "[3/7] Removing old installation (nuclear mode)..." -ForegroundColor Yellow
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
Write-Host "[4/7] Creating fresh directory..." -ForegroundColor Green
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
attrib +h $InstallDir  # hide it

Write-Host "[5/7] Downloading latest agent..." -ForegroundColor Green
try {
    Invoke-WebRequest -Uri $ScriptUrl -OutFile "$InstallDir\pc_wipe_agent.py" -UseBasicParsing
} catch {
    Write-Error "Failed to download agent script. Check internet or URL: $_"
    exit 1
}

Write-Host "[6/7] Setting up Python venv + dependencies..." -ForegroundColor Green
& python -m venv "$InstallDir\venv" --clear
& "$InstallDir\venv\Scripts\pip.exe" install --quiet --upgrade pip 2>$null
& "$InstallDir\venv\Scripts\pip.exe" install --quiet flask cryptography

# === STEP 5: Download and extract NSSM ===
Write-Host "[7/7] Installing NSSM service manager..." -ForegroundColor Green
$NssmZip = "$env:TEMP\nssm.zip"
$NssmExtract = "$env:TEMP\nssm_extract"
$NssmPath = "$InstallDir\nssm.exe"

try {
    Write-Host "    Downloading NSSM from official source..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip -UseBasicParsing
    
    Write-Host "    Extracting NSSM..." -ForegroundColor Gray
    Expand-Archive -Path $NssmZip -DestinationPath $NssmExtract -Force
    
    # Detect architecture and copy correct binary
    if ([Environment]::Is64BitOperatingSystem) {
        $NssmExe = Get-ChildItem -Path $NssmExtract -Filter "nssm.exe" -Recurse | Where-Object { $_.FullName -like "*win64*" } | Select-Object -First 1
    } else {
        $NssmExe = Get-ChildItem -Path $NssmExtract -Filter "nssm.exe" -Recurse | Where-Object { $_.FullName -like "*win32*" } | Select-Object -First 1
    }
    
    if (-not $NssmExe) {
        Write-Error "Could not find NSSM executable in archive"
        exit 1
    }
    
    Copy-Item $NssmExe.FullName -Destination $NssmPath -Force
    
    # Cleanup
    Remove-Item $NssmZip -Force -ErrorAction SilentlyContinue
    Remove-Item $NssmExtract -Recurse -Force -ErrorAction SilentlyContinue
    
} catch {
    Write-Error "Failed to download/extract NSSM: $_"
    Write-Host "`nTrying fallback method..." -ForegroundColor Yellow
    
    # Fallback: Try the GitHub raw link as backup
    try {
        $FallbackUrl = "https://raw.githubusercontent.com/Mona-3024/windows_pc_agent/main/nssm.exe"
        Invoke-WebRequest -Uri $FallbackUrl -OutFile $NssmPath -UseBasicParsing
    } catch {
        Write-Error "All download methods failed. Please manually download NSSM from https://nssm.cc/download"
        exit 1
    }
}

if (-not (Test-Path $NssmPath)) {
    Write-Error "NSSM installation failed. File not found at $NssmPath"
    exit 1
}

# === STEP 6: Install service ===
Write-Host "    Registering Windows service..." -ForegroundColor Gray
& $NssmPath install $ServiceName `"$InstallDir\venv\Scripts\python.exe`" `"$InstallDir\pc_wipe_agent.py`"
& $NssmPath set $ServiceName DisplayName "Windows Security Agent"
& $NssmPath set $ServiceName Description "Secure data sanitization service"
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName AppDirectory $InstallDir
& $NssmPath set $ServiceName AppStdout "$InstallDir\service.log"
& $NssmPath set $ServiceName AppStderr "$InstallDir\error.log"
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 1048576

Write-Host "    Starting service..." -ForegroundColor Gray
Start-Service $ServiceName

# Wait for service to start
Start-Sleep -Seconds 3

# === STEP 7: Verify installation ===
$ServiceStatus = Get-Service $ServiceName -ErrorAction SilentlyContinue
if ($ServiceStatus.Status -eq "Running") {
    Write-Host "`nSUCCESS! Agent is running" -ForegroundColor Green
} else {
    Write-Warning "Service installed but not running. Check logs at $InstallDir\error.log"
}

# === DONE ===
Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host " Service: $ServiceName (Status: $($ServiceStatus.Status))"
Write-Host " Location: $InstallDir"
Write-Host " API: http://$(hostname):5055/"
Write-Host " Test: curl http://localhost:5055/?key=admin"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Logs: $InstallDir\service.log" -ForegroundColor Gray
Write-Host "Reboot not required. Agent survives reboot." -ForegroundColor Gray
