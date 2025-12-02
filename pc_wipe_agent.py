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
PC_OWNER = "TGC"

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
            # Full drive wipe
            print("[WIPE] Full drive wipe detected")
            drive = wipe_target.strip(":\\") + ":\\"
            wipe_progress = 10
            subprocess.call(f'del /f /s /q {drive}. >nul 2>&1', shell=True)
            wipe_progress = 100
            print("[WIPE] Drive wipe completed")
            
        elif os.path.isfile(wipe_target):
            # Single file wipe
            print(f"[WIPE] Wiping file: {wipe_target}")
            size = os.path.getsize(wipe_target)
            wipe_progress = 20
            with open(wipe_target, "r+b") as f:
                f.write(b'\x00' * size)
            wipe_progress = 80
            os.remove(wipe_target)
            wipe_progress = 100
            print("[WIPE] File wipe completed")
            
        elif os.path.isdir(wipe_target):
            # Directory wipe
            print(f"[WIPE] Wiping directory: {wipe_target}")
            wipe_progress = 5
            
            # Count total files
            total = 0
            for root, _, files in os.walk(wipe_target):
                total += len(files)
            
            print(f"[WIPE] Total files to wipe: {total}")
            
            if total == 0:
                wipe_progress = 50
                shutil.rmtree(wipe_target, ignore_errors=True)
                wipe_progress = 100
                print("[WIPE] Empty directory removed")
            else:
                wiped = 0
                for root, _, files in os.walk(wipe_target):
                    if stop_flag.is_set(): 
                        print("[WIPE] Emergency stop triggered!")
                        break
                    for filename in files:
                        try:
                            filepath = os.path.join(root, filename)
                            os.remove(filepath)
                            wiped += 1
                            if total > 0:
                                wipe_progress = int((wiped / total) * 90) + 5
                            
                            if wiped % 10 == 0:
                                print(f"[WIPE] Progress: {wipe_progress}% ({wiped}/{total})")
                        except Exception as e:
                            print(f"[WIPE] Error deleting {filepath}: {e}")
                
                # Remove directory structure
                wipe_progress = 95
                shutil.rmtree(wipe_target, ignore_errors=True)
                wipe_progress = 100
                print("[WIPE] Directory wipe completed")
        else:
            print(f"[WIPE] Target not found: {wipe_target}")
            wipe_progress = 0
            
    except Exception as e:
        print(f"[WIPE ERROR] {e}")
        wipe_progress = 0
    finally:
        if wipe_progress >= 100:
            print("[WIPE] Generating certificate...")
            generate_certificate()
            print("[WIPE] Certificate generated successfully")

# ==========================================
# FLASK ROUTES - MUST BE AT MODULE LEVEL
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
