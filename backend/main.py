import subprocess
import random
import os
import threading
import time
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

print(">>> SYSTEM CHECK: Initializing MAC Rotator...")

# Global State
all_logs = []
log_lock = threading.Lock()
is_running = False
current_config = {"interface": None, "interval": 0}

def log_event(message, level="INFO"):
    timestamp = time.time()
    entry = {"message": f"[{level}] {message}", "timestamp": timestamp}
    with log_lock:
        all_logs.append(entry)
    print(f"[{level}] {message}")

def get_default_interface():
    """Detects the interface used for default internet connection."""
    try:
        result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
        if result.returncode == 0 and "dev" in result.stdout:
            parts = result.stdout.split()
            if "dev" in parts:
                idx = parts.index("dev")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
    except Exception:
        return None
    return None

def interface_exists(interface):
    """Check if an interface exists on the system."""
    try:
        result = subprocess.run(["ip", "link", "show", interface], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False

def generate_random_mac():
    first_byte = random.randint(1, 254) & 0xFE
    if first_byte == 0: first_byte = 2
    mac = [first_byte]
    for _ in range(5):
        mac.append(random.randint(0, 255))
    return ":".join(f"{b:02x}" for b in mac)

def change_mac_address(interface, mac_address):
    if os.name == 'nt':
        raise Exception("Windows is not supported. This tool requires Linux (ip command).")
    
    if os.geteuid() != 0:
        raise Exception("Root privileges required. Run with 'sudo'.")

    try:
        # Bring down
        p1 = subprocess.run(["ip", "link", "set", interface, "down"], capture_output=True, text=True)
        if p1.returncode != 0:
            raise Exception(f"Failed to bring down interface: {p1.stderr}")
        
        # Change MAC
        p2 = subprocess.run(["ip", "link", "set", interface, "address", mac_address], capture_output=True, text=True)
        if p2.returncode != 0:
            # Attempt to bring up again before raising error
            subprocess.run(["ip", "link", "set", interface, "up"], capture_output=True)
            raise Exception(f"Failed to change MAC (Driver/Hardware restriction?): {p2.stderr}")
        
        # Bring up
        p3 = subprocess.run(["ip", "link", "set", interface, "up"], capture_output=True, text=True)
        if p3.returncode != 0:
            raise Exception(f"Failed to bring up interface: {p3.stderr}")
            
        return True
    except Exception as e:
        raise e

def rotation_loop(interface, interval):
    global is_running
    log_event(f"Rotation started on {interface}. Interval: {interval}s", "WARN")
    
    # Safety Check: Warn if rotating the default gateway interface
    default_iface = get_default_interface()
    if default_iface and interface == default_iface:
        log_event(f"CRITICAL: You are rotating the default connection interface ({interface}). You will lose connectivity!", "CRITICAL")
    
    count = 0
    while is_running:
        try:
            new_mac = generate_random_mac()
            log_event(f"Attempt {count+1}: Changing to {new_mac}")
            
            change_mac_address(interface, new_mac)
            
            log_event(f"SUCCESS: MAC changed to {new_mac}", "SUCCESS")
            count += 1
        except Exception as e:
            error_msg = f"CRITICAL ERROR: {str(e)}"
            log_event(error_msg, "ERROR")
            is_running = False
            break
        
        # Interruptible sleep
        for _ in range(interval * 10):
            if not is_running:
                break
            time.sleep(0.1)
    
    log_event("Rotation stopped.", "INFO")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            try:
                # Calculate the correct path relative to this script's location
                script_dir = os.path.dirname(os.path.abspath(__file__))
                project_root = os.path.dirname(script_dir)  # Go up one level to project root
                frontend_path = os.path.join(project_root, 'frontend', 'index.html')

                with open(frontend_path, 'r') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(content.encode())
                return
            except FileNotFoundError:
                error_msg = f"Frontend not found. Expected at: {frontend_path}. Ensure frontend/index.html exists."
                print(f"ERROR: {error_msg}")
                self.send_error(404, error_msg)
                return

        if self.path == '/api/status':
            self.send_json({"is_running": is_running, "config": current_config if is_running else None})
        elif self.path == '/api/logs':
            with log_lock:
                self.send_json(all_logs[-50:])
        elif self.path == '/api/interfaces':
            self.send_json({
                "interfaces": ["eth0", "wlan0"], 
                "warning": "Do not rotate the interface you are currently connected to."
            })
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    try:
        print(">>> INITIALIZING SERVER...")
        if os.name == 'nt':
            print("!!! WARNING: Windows detected. This tool will not function on Windows.")
        if os.geteuid() != 0:
            print("!!! WARNING: Not running as root. MAC changing will fail. Use 'sudo'.")
        else:
            print(">>> ROOT PRIVILEGES DETECTED. Ready to change MAC addresses.")
            
        server = HTTPServer(('0.0.0.0', 8000), Handler)
        print(">>> SERVER IS RUNNING. Waiting for commands...")
        server.serve_forever()
    except Exception as e:
        print(f"\n!!! CRITICAL FAILURE: {e}")
        input("Press Enter to exit...")