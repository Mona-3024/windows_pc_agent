# Secure Wipe Agent - Installation Script with Proper Cleanup
# Run as Administrator

$ErrorActionPreference = "Stop"
$InstallDir = "C:\ProgramData\SecureWipeAgent"
$ServiceName = "SecureWipeAgent"

Write-Host "Installing Secure Wipe Agent..." -ForegroundColor Cyan

# Step 1: Stop and remove existing service
Write-Host "Stopping existing service if running..." -ForegroundColor Yellow
try {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "Found existing service, stopping..." -ForegroundColor Yellow
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        
        # Kill any python processes from the install directory
        Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -like "$InstallDir*"
        } | Stop-Process -Force -ErrorAction SilentlyContinue
        
        Start-Sleep -Seconds 2
        
        # Remove service
        sc.exe delete $ServiceName | Out-Null
        Write-Host "Existing service removed" -ForegroundColor Green
        Start-Sleep -Seconds 3
    }
} catch {
    Write-Host "No existing service found or already stopped" -ForegroundColor Gray
}

# Step 2: Force close any file handles in the directory
Write-Host "Closing file handles..." -ForegroundColor Yellow
if (Test-Path $InstallDir) {
    # Kill any python processes
    Get-Process -Name python* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    
    # Remove read-only attributes
    Get-ChildItem -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            $_.Attributes = 'Normal'
        } catch {}
    }
}

# Step 3: Aggressive directory removal
Write-Host "Removing old installation..." -ForegroundColor Yellow
if (Test-Path $InstallDir) {
    try {
        # First attempt: PowerShell Remove-Item
        Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
    } catch {}
    
    Start-Sleep -Seconds 1
    
    # Second attempt: CMD rmdir
    if (Test-Path $InstallDir) {
        cmd /c "rmdir /s /q `"$InstallDir`"" 2>$null
    }
    
    Start-Sleep -Seconds 1
    
    # Third attempt: Delete files one by one
    if (Test-Path $InstallDir) {
        Get-ChildItem -Path $InstallDir -Recurse -Force -ErrorAction SilentlyContinue | 
            Sort-Object -Property FullName -Descending | 
            ForEach-Object {
                try {
                    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
                } catch {}
            }
        
        # Final attempt to remove directory
        Remove-Item $InstallDir -Force -ErrorAction SilentlyContinue
    }
}

# Step 4: Create fresh directory
Write-Host "Creating installation directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

# Step 5: Download the agent script
Write-Host "Downloading latest pc_wipe_agent.py..." -ForegroundColor Yellow
$ScriptUrl = "https://raw.githubusercontent.com/Mona-3024/windows_pc_agent/refs/heads/main/pc_wipe_agent.py"
$ScriptPath = Join-Path $InstallDir "pc_wipe_agent.py"

try {
    Invoke-WebRequest -Uri $ScriptUrl -OutFile $ScriptPath -UseBasicParsing
    Write-Host "Download complete" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to download script - $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Step 6: Setup Python virtual environment
Write-Host "Setting up Python virtual environment..." -ForegroundColor Yellow

# Check if Python is installed
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "Python 3") {
            $pythonCmd = $cmd
            Write-Host "Found Python: $version" -ForegroundColor Green
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "ERROR: Python 3 is not installed!" -ForegroundColor Red
    Write-Host "Please install Python 3 from https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# Create virtual environment
$venvPath = Join-Path $InstallDir "venv"
try {
    & $pythonCmd -m venv $venvPath --clear
    Write-Host "Virtual environment created" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to create virtual environment - $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Step 7: Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
$pipPath = Join-Path $venvPath "Scripts\pip.exe"
$pythonVenv = Join-Path $venvPath "Scripts\python.exe"

try {
    & $pipPath install --upgrade pip setuptools wheel --quiet
    & $pipPath install flask cryptography --quiet
    Write-Host "Dependencies installed successfully" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to install dependencies - $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Step 8: Create NSSM service wrapper script
Write-Host "Creating service wrapper..." -ForegroundColor Yellow
$wrapperScript = @"
import sys
import os

# Change to install directory
os.chdir(r'$InstallDir')

# Run the agent
exec(open('pc_wipe_agent.py').read())
"@

$wrapperPath = Join-Path $InstallDir "service_wrapper.py"
Set-Content -Path $wrapperPath -Value $wrapperScript -Encoding UTF8

# Step 9: Install as Windows Service using sc.exe
Write-Host "Installing Windows Service..." -ForegroundColor Yellow

$serviceBatch = Join-Path $InstallDir "start_service.bat"
$batchContent = @"
@echo off
cd /d "$InstallDir"
"$pythonVenv" service_wrapper.py
"@
Set-Content -Path $serviceBatch -Value $batchContent -Encoding ASCII

# Create service
$scCommand = "sc.exe create $ServiceName binPath= `"$serviceBatch`" start= auto DisplayName= `"Secure Wipe Agent`""
Invoke-Expression $scCommand | Out-Null

# Configure service recovery options
sc.exe failure $ServiceName reset= 86400 actions= restart/60000/restart/60000/restart/60000 | Out-Null

Write-Host "Service installed successfully" -ForegroundColor Green

# Step 10: Start the service
Write-Host "Starting service..." -ForegroundColor Yellow
try {
    Start-Service -Name $ServiceName
    Start-Sleep -Seconds 3
    
    $service = Get-Service -Name $ServiceName
    if ($service.Status -eq "Running") {
        Write-Host "Service started successfully!" -ForegroundColor Green
    } else {
        Write-Host "WARNING: Service is not running. Status: $($service.Status)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "ERROR: Failed to start service - $($_.Exception.Message)" -ForegroundColor Red
}

# Step 11: Display completion info
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Installation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Service Name: $ServiceName" -ForegroundColor White
Write-Host "Install Directory: $InstallDir" -ForegroundColor White
Write-Host "Default Port: 5055" -ForegroundColor White
Write-Host "`nManagement Commands:" -ForegroundColor Yellow
Write-Host "  Start:   Start-Service $ServiceName" -ForegroundColor White
Write-Host "  Stop:    Stop-Service $ServiceName" -ForegroundColor White
Write-Host "  Status:  Get-Service $ServiceName" -ForegroundColor White
Write-Host "  Logs:    Get-Content $InstallDir\service.log -Tail 50" -ForegroundColor White
Write-Host "========================================`n" -ForegroundColor Cyan
