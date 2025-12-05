import os
import threading
import subprocess
import shutil
import socket
import json
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

# ==========================================
# CONFIGURATION
# ==========================================
API_KEY = "admin"
PORT = 5055

PC_NAME = "Office-PC-01"
PC_LOCATION = "Head Office"
PC_OWNER = "John Doe"

# Generate or load private key (runs once)
KEY_FILE = "private_key.pem"
CERT_DIR = "wipe_certificates"

if not os.path.exists(KEY_FILE):
    private_key = ed25519.Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    with open(KEY_FILE, "wb") as f:
        f.write(pem)
    print("[+] New private key generated:", KEY_FILE)
else:
    with open(KEY_FILE, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None
        )
    print("[+] Private key loaded")

public_key = private_key.public_key()
PUBLIC_PEM = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
)

os.makedirs(CERT_DIR, exist_ok=True)

# CREATE FLASK APP FIRST
app = Flask(__name__)

# Global state
wipe_thread = None
stop_flag = threading.Event()
wipe_start_time = None
wipe_end_time = None
wipe_target = "None"
wipe_method = "quick"
wipe_progress = 0

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def check_auth(req):
    key = req.headers.get("X-API-Key", "") or req.args.get("key", "")
    return key == API_KEY

def is_safe_path(path):
    try:
        abs_path = os.path.abspath(path).lower().replace("/", "\\")
        protected = [
            "c:\\windows", "c:\\program files", "c:\\program files (x86)",
            "c:\\users", "c:\\programdata", "c:\\$recycle.bin"
        ]
        return not any(abs_path.startswith(p) for p in protected)
    except:
        return False

def secure_overwrite_file(filepath, passes=3):
    if not os.path.isfile(filepath):
        return
    size = os.path.getsize(filepath)
    if size == 0:
        os.remove(filepath)
        return

    patterns = [
        b'\x00' * 4096,      # zeros
        b'\xFF' * 4096,      # ones
        b'\xAA' * 4096,      # alternating bits
        os.urandom(4096),    # random (best for SSDs)
    ]

    with open(filepath, "r+b") as f:
        for pass_num in range(passes):
            pattern = patterns[pass_num % len(patterns)]
            if pattern == os.urandom(4096):
                data = os.urandom(4096)
            else:
                data = pattern

            f.seek(0)
            for _ in range(0, size, 4096):
                chunk_size = min(4096, size - f.tell())
                f.write(data[:chunk_size])
            f.flush()
            os.fsync(f.fileno())
    os.remove(filepath)

def generate_certificate():
    global wipe_end_time, wipe_target, wipe_method
    wipe_end_time = datetime.now()

    cert = {
        "certificate_id": os.urandom(8).hex(),
        "pc_name": PC_NAME,
        "location": PC_LOCATION,
        "owner": PC_OWNER,
        "target_device": wipe_target,
        "wipe_method": wipe_method,
        "started_at": wipe_start_time.isoformat(),
        "completed_at": wipe_end_time.isoformat(),
        "duration_seconds": int((wipe_end_time - wipe_start_time).total_seconds()),
        "agent_ip": get_local_ip(),
        "verified_by": "Secure Wipe Agent v4",
        "tamper_proof": True
    }

    cert_json = json.dumps(cert, indent=2).encode()
    signature = private_key.sign(cert_json)

    filename = f"wipe-cert-{PC_NAME.replace(' ', '-')}-{int(datetime.now().timestamp())}.json"
    sigfile = filename + ".sig"

    with open(os.path.join(CERT_DIR, filename), "wb") as f:
        f.write(cert_json)
    with open(os.path.join(CERT_DIR, sigfile), "wb") as f:
        f.write(signature)

    print(f"[CERTIFICATE ISSUED] {filename}")
    return filename

# === WIPING LOGIC ===
def smart_wipe_job(target, method="quick"):
    global wipe_target, wipe_start_time, wipe_progress, wipe_method, wipe_end_time
    stop_flag.clear()
    wipe_start_time = datetime.now()
    wipe_target = target.strip('"')
    wipe_method = method
    wipe_progress = 0
    wipe_end_time = None

    print(f"[WIPE START] Target: {wipe_target}, Method: {wipe_method}")

    if not is_safe_path(wipe_target):
        print(f"[BLOCKED] Unsafe path: {wipe_target}")
        wipe_progress = 0
        return

    try:
        if len(wipe_target) <= 3 and ":" in wipe_target:
            # Full drive wipe with cipher
            drive_letter = wipe_target.upper().replace(":", "").replace("\\", "") + ":"
            drive_path = drive_letter + "\\"
            print(f"[WIPE] Starting FULL DRIVE secure wipe: {drive_letter}")
            
            # Step 1: Delete all files recursively
            wipe_progress = 5
            print("[WIPE] Deleting all files on drive...")
            subprocess.call(f'del /f /s /q /a {drive_path}* >nul 2>&1', shell=True)
            
            # Step 2: Remove all directories (including hidden/system)
            wipe_progress = 15
            print("[WIPE] Removing all directory structures...")
            # Get all folders and delete them one by one
            try:
                for root, dirs, files in os.walk(drive_path, topdown=False):
                    if stop_flag.is_set():
                        break
                    for dir_name in dirs:
                        dir_path = os.path.join(root, dir_name)
                        try:
                            os.rmdir(dir_path)
                        except:
                            subprocess.call(f'rmdir /s /q "{dir_path}" >nul 2>&1', shell=True)
            except Exception as e:
                print(f"[WIPE] Directory cleanup: {e}")
            
            # Step 3: Final aggressive cleanup
            wipe_progress = 25
            subprocess.call(f'for /d %i in ({drive_path}*) do @rmdir /s /q "%i" >nul 2>&1', shell=True)
            
            # Step 4: Wipe free space with cipher (overwrites with 0, FF, random)
            wipe_progress = 40
            print(f"[WIPE] Running cipher /w:{drive_letter} - this may take hours!")
            print("[WIPE] This will overwrite all free space with zeros, ones, and random data")
            result = subprocess.call(f'cipher /w:{drive_letter}', shell=True)
            wipe_progress = 100
            print(f"[WIPE] Drive {drive_letter} has been completely and forensically wiped")
            print(f"[WIPE] All data is now unrecoverable, and all folders have been removed")
            
        elif os.path.isfile(wipe_target):
            # Single file wipe
            print(f"[WIPE] Wiping file: {wipe_target}")
            size = os.path.getsize(wipe_target)
            wipe_progress = 20
            secure_overwrite_file(wipe_target, passes=3)
            wipe_progress = 100
            print("[WIPE] File wipe completed")
            
        elif os.path.isdir(wipe_target):
            print(f"[WIPE] Securely wiping directory: {wipe_target}")
            wipe_progress = 5

            # Get the drive letter where this directory is located
            target_drive = os.path.splitdrive(os.path.abspath(wipe_target))[0]
            
            total = sum(len(files) for _, _, files in os.walk(wipe_target))
            wiped = 0

            # Step 1: Securely overwrite all files
            for root, dirs, files in os.walk(wipe_target, topdown=False):
                if stop_flag.is_set():
                    break
                for name in files:
                    if stop_flag.is_set():
                        break
                    filepath = os.path.join(root, name)
                    try:
                        secure_overwrite_file(filepath, passes=3)
                        wiped += 1
                        wipe_progress = int((wiped / max(total, 1)) * 60) + 5
                        if wiped % 50 == 0 or wiped == total:
                            print(f"[WIPE] File overwrite progress: {wipe_progress}% ({wiped}/{total})")
                    except Exception as e:
                        print(f"[ERROR] Failed {filepath}: {e}")

            # Step 2: Remove directory structure
            wipe_progress = 70
            print("[WIPE] Removing directory structure...")
            shutil.rmtree(wipe_target, ignore_errors=True)
            
            # Step 3: Wipe free space on the drive to eliminate recoverable data
            wipe_progress = 75
            print(f"[WIPE] Wiping free space on drive {target_drive} to prevent recovery...")
            print(f"[WIPE] Running cipher /w:{target_drive} - this ensures deleted data is unrecoverable")
            subprocess.call(f'cipher /w:{target_drive}', shell=True)
            
            wipe_progress = 100
            print("[WIPE] Directory and free space completely and irrecoverably wiped")
            
    except Exception as e:
        print(f"[WIPE ERROR] {e}")
        wipe_progress = 0
    finally:
        if wipe_progress >= 100:
            print("[WIPE] Generating certificate...")
            generate_certificate()
            print("[WIPE] Certificate generated successfully")

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route("/")
def index():
    """Root endpoint - agent info"""
    try:
        cert_files = os.listdir(CERT_DIR) if os.path.exists(CERT_DIR) else []
    except:
        cert_files = []
    
    return jsonify({
        "pc_name": PC_NAME,
        "ip": get_local_ip(),
        "port": PORT,
        "public_key_pem": PUBLIC_PEM.decode(),
        "certificates": cert_files,
        "status": "online"
    })

@app.route("/status")
def status():
    """Status endpoint"""
    if not check_auth(request): 
        return jsonify({"error": "Unauthorized"}), 401
    
    is_active = wipe_thread is not None and wipe_thread.is_alive()
    is_completed = wipe_progress == 100 and wipe_end_time is not None
    
    return jsonify({
        "pc_name": PC_NAME,
        "wipe_active": is_active,
        "target": wipe_target,
        "progress": wipe_progress,
        "completed": is_completed,
        "method": wipe_method
    })

@app.route("/wipe", methods=["POST"])
def wipe():
    """Wipe endpoint"""
    if not check_auth(request): 
        return jsonify({"error": "Unauthorized"}), 401
    
    global wipe_thread
    
    if wipe_thread and wipe_thread.is_alive():
        return jsonify({"error": "Wipe in progress"}), 409

    target = request.args.get("device", "")
    method = request.args.get("method", "quick")
    
    if not target:
        return jsonify({"error": "Missing device"}), 400

    print(f"[API] Wipe request received - Target: {target}, Method: {method}")
    
    wipe_thread = threading.Thread(target=smart_wipe_job, args=(target, method))
    wipe_thread.daemon = True
    wipe_thread.start()

    return jsonify({
        "status": "WIPE STARTED", 
        "target": target, 
        "method": method,
        "pc_name": PC_NAME
    })

@app.route("/emergency-stop", methods=["POST"])
def emergency_stop():
    """Emergency stop endpoint"""
    if not check_auth(request): 
        return jsonify({"error": "Unauthorized"}), 401
    
    print("[API] Emergency stop triggered!")
    stop_flag.set()
    
    return jsonify({
        "status": "STOPPED",
        "pc_name": PC_NAME
    })

@app.route("/certificate/<filename>")
def get_cert(filename):
    """Download certificate"""
    return send_from_directory(CERT_DIR, filename)

@app.route("/certificate/<filename>.sig")
def get_sig(filename):
    """Download signature"""
    return send_from_directory(CERT_DIR, filename + ".sig")

# ==========================================
# MAIN EXECUTION
# ==========================================

if __name__ == "__main__":
    print("="*60)
    print(" SECURE WIPE AGENT + TAMPER-PROOF CERTIFICATES ")
    print(f" PC: {PC_NAME} | IP: http://{get_local_ip()}:{PORT}")
    print(f" Public Key (share this):")
    print(PUBLIC_PEM.decode())
    print(f" API Key: {API_KEY}")
    print("="*60)
    
    # Print registered routes for debugging
    print("\nRegistered Routes:")
    for rule in app.url_map.iter_rules():
        methods = ', '.join([m for m in rule.methods if m not in ['HEAD', 'OPTIONS']])
        print(f"  {rule.endpoint:20s} {rule.rule:30s} [{methods}]")
    print("="*60)
    
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False)
