import os
import threading
import subprocess
import psutil
import shutil
from flask import Flask, request, jsonify

# ==========================================
# CONFIGURATION
# ==========================================
API_KEY = "admin"       # <-- CHANGE THIS to match your Android App key
PORT = 5050

app = Flask(__name__)

# Global control variables
wipe_thread = None
stop_flag = False

# ==========================================
# HELPER: AUTH & SAFETY
# ==========================================
def check_auth(req):
    """Verifies the API key from headers."""
    key = req.headers.get("X-API-Key", "")
    return key == API_KEY

def is_safe_path(path):
    """
    Prevents accidental wiping of critical system paths.
    Returns True if safe, False if unsafe.
    """
    path = os.path.abspath(path).lower()
    
    # List of protected paths (Customize as needed)
    protected = [
        "c:\\windows",
        "c:\\program files",
        "c:\\program files (x86)",
        os.path.abspath(__file__).lower() # Don't wipe the script itself
    ]
    
    # 1. Check if path matches or is inside a protected folder
    for p in protected:
        if path.startswith(p):
            return False
            
    # 2. Protect C:\ root from accidental folder/file mode wipes
    # (Drive mode handles root separately, but we block C: root generally for safety)
    if path == "c:\\" or path == "c:":
        return False

    return True

# ==========================================
# CORE WIPING LOGIC
# ==========================================

def secure_delete_file(file_path):
    """
    Overwrites a file with zeros before deleting it.
    """
    global stop_flag
    try:
        if not os.path.exists(file_path): return

        # Get file size
        length = os.path.getsize(file_path)
        
        # Overwrite content
        with open(file_path, "wb") as f:
            if stop_flag: return
            f.seek(0)
            f.write(b'\x00' * length)
            f.flush()
            os.fsync(f.fileno())
                
        # Delete file
        os.remove(file_path)
        print(f"[DELETED FILE] {file_path}")
        
    except Exception as e:
        print(f"[ERROR] Failed to wipe file {file_path}: {e}")

def task_wipe_folder(folder_path):
    """
    Recursively wipes all files in a folder, then removes the folder structure.
    """
    global stop_flag
    print(f"[INFO] Starting Folder Wipe: {folder_path}")
    
    # 1. Walk and secure delete files
    for root, dirs, files in os.walk(folder_path, topdown=False):
        if stop_flag: 
            print("[STOP] Emergency stop triggered.")
            return

        for name in files:
            file_path = os.path.join(root, name)
            secure_delete_file(file_path)

        # 2. Remove directories after they are empty
        for name in dirs:
            dir_path = os.path.join(root, name)
            try:
                os.rmdir(dir_path)
            except:
                pass

    # 3. Remove the root folder itself
    try:
        if not stop_flag:
            shutil.rmtree(folder_path, ignore_errors=True)
            print(f"[INFO] Folder structure removed: {folder_path}")
    except Exception as e:
        print(f"[ERROR] Could not remove root folder: {e}")

def task_wipe_drive(drive_letter):
    """
    Wipes an entire drive by deleting files normally first, 
    then filling all remaining free space with garbage data.
    """
    global stop_flag
    
    # Ensure format "D:"
    if ":" not in drive_letter:
        drive_letter = drive_letter[0] + ":"
        
    print(f"[INFO] Starting Drive Wipe: {drive_letter}")

    try:
        # 1. Quick Delete (Standard OS delete) to free up space
        print("[STEP 1] Deleting existing files...")
        # Force delete everything on the drive
        subprocess.call(f"del /f /s /q {drive_letter}\\*.*", shell=True)
        
        # 2. Fill Free Space (The actual "Wipe")
        print("[STEP 2] Overwriting free space...")
        zero_file = os.path.join(drive_letter + "\\", "wipe_zero.bin")
        
        # Write 100MB chunks until full
        block_size_mb = 100 
        
        with open(zero_file, "wb") as f:
            while True:
                if stop_flag:
                    print("[STOP] Emergency stop triggered.")
                    break
                try:
                    f.write(b'\x00' * (block_size_mb * 1024 * 1024))
                except OSError:
                    # Disk is full
                    break
                    
        print("[INFO] Drive wipe complete. Cleaning up...")
        
    except Exception as e:
        print(f"[ERROR] Drive wipe failed: {e}")
    finally:
        # Try to remove the massive zero file
        try:
            if os.path.exists(zero_file):
                os.remove(zero_file)
        except:
            pass

# ==========================================
# THREAD DISPATCHER (The Smart Logic)
# ==========================================
def smart_wipe_job(path_input):
    global stop_flag
    stop_flag = False
    
    # Cleanup input (remove quotes if pasted)
    path = path_input.strip().replace('"', '')

    # Safety Check
    if not is_safe_path(path):
        print(f"[BLOCKED] Attempt to wipe protected path: {path}")
        return

    # --- AUTO-DETECTION ---
    
    # 1. Check if it looks like a Drive (e.g., "D:", "E:\")
    # Logic: Short length and contains a colon
    if len(path) <= 3 and ":" in path:
        print(f"[DETECTED] Target is a DRIVE: {path}")
        task_wipe_drive(path)
        return

    # 2. Check if it is an existing Folder
    if os.path.isdir(path):
        print(f"[DETECTED] Target is a FOLDER: {path}")
        task_wipe_folder(path)
        return

    # 3. Check if it is an existing File
    if os.path.isfile(path):
        print(f"[DETECTED] Target is a FILE: {path}")
        secure_delete_file(path)
        return

    # 4. Fallback/Error
    print(f"[ERROR] Path not found or unknown type: {path}")


# ==========================================
# API ENDPOINTS
# ==========================================

@app.route("/status", methods=["GET"])
def status():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    
    is_active = wipe_thread.is_alive() if wipe_thread else False
    return jsonify({"status": "online", "wipe_active": is_active})

@app.route("/list-devices", methods=["GET"])
def list_devices():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    
    drives = []
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts or p.fstype == '': continue
        drives.append({"device": p.device, "mount": p.mountpoint})
    return jsonify({"devices": drives})

@app.route("/wipe", methods=["POST"])
def wipe():
    """
    Receives the wipe command.
    COMPATIBLE with Old App: Expects query parameters '?device=X&method=Y'
    """
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401

    # 1. Get data from Query Parameters (Standard HTTP POST from Android Volley/HttpUrlConnection)
    path_input = request.args.get("device", "")
    method = request.args.get("method", "zero") # (Unused in smart mode, but kept for compatibility)

    if not path_input:
        return jsonify({"error": "Missing 'device' parameter"}), 400

    global wipe_thread
    if wipe_thread and wipe_thread.is_alive():
        return jsonify({"error": "A wipe task is already running"}), 409

    # 2. Start the Smart Wipe Logic in a background thread
    wipe_thread = threading.Thread(target=smart_wipe_job, args=(path_input,))
    wipe_thread.start()

    return jsonify({
        "status": "wipe_started",
        "target_received": path_input,
        "message": "Agent is determining type (File/Folder/Drive)..."
    })

@app.route("/emergency-stop", methods=["POST"])
def emergency_stop():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    
    global stop_flag
    stop_flag = True
    print("[SIGNAL] Emergency Stop Received")
    return jsonify({"status": "stopping_process"})

if __name__ == "__main__":
    print("========================================")
    print(f" PC WIPE AGENT (Smart Mode) ")
    print(f" Listening on http://0.0.0.0:{PORT}")
    print(f" API Key: {API_KEY}")
    print("========================================")
    app.run(host="0.0.0.0", port=PORT)
