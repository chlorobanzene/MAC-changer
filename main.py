import subprocess
import random
import os
import threading
import time
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

print(">>> SYSTEM CHECK: Starting diagnostics...")

# Simple print-based logging to avoid config crashes
def log_event(message):
    print(f"[LOG] {message}")
    # We store logs in memory for the UI
    with log_lock:
        all_logs.append({"message": message, "timestamp": time.time()})

all_logs = []
log_lock = threading.Lock()
is_running = False
current_config = {"interface": None, "interval": 0}

def generate_random_mac():
    first_byte = random.randint(1, 254) & 0xFE
    if first_byte == 0: first_byte = 2
    mac = [first_byte]
    for _ in range(5):
        mac.append(random.randint(0, 255))
    return ":".join(f"{b:02x}" for b in mac)

def change_mac_address(interface, mac_address):
    print(f">>> TRYING TO CHANGE MAC ON {interface} TO {mac_address}")
    
    # Check if running on Windows (common crash point)
    if os.name == 'nt':
        raise Exception("ERROR: Windows detected. This script requires Linux commands (ip link).")

    # Check for root
    if os.geteuid() != 0:
        raise Exception("ERROR: NOT ROOT. You must run this script with 'sudo python3 main.py'.")

    try:
        # Step 1: Bring down
        p1 = subprocess.run(["ip", "link", "set", interface, "down"], capture_output=True, text=True)
        if p1.returncode != 0:
            raise Exception(f"Failed to bring down interface: {p1.stderr}")
        
        # Step 2: Change MAC
        p2 = subprocess.run(["ip", "link", "set", interface, "address", mac_address], capture_output=True, text=True)
        if p2.returncode != 0:
            raise Exception(f"Failed to change MAC (Hardware/Driver might block this): {p2.stderr}")
        
        # Step 3: Bring up
        p3 = subprocess.run(["ip", "link", "set", interface, "up"], capture_output=True, text=True)
        if p3.returncode != 0:
            raise Exception(f"Failed to bring up interface: {p3.stderr}")
            
        print(">>> SUCCESS: MAC address changed.")
        return True
    except Exception as e:
        raise e

def rotation_loop(interface, interval):
    global is_running
    log_event(f"Rotation started on {interface}. Interval: {interval}s")
    count = 0
    while is_running:
        try:
            new_mac = generate_random_mac()
            log_event(f"Attempt {count+1}: Changing to {new_mac}")
            change_mac_address(interface, new_mac)
            log_event(f"SUCCESS: MAC is now {new_mac}")
            count += 1
        except Exception as e:
            error_msg = f"CRITICAL ERROR: {str(e)}"
            log_event(error_msg)
            print(f"!!! {error_msg}")
            is_running = False
            break
        
        # Interruptible sleep
        for _ in range(interval * 10):
            if not is_running: break
            time.sleep(0.1)
    
    log_event("Rotation stopped.")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/status':
            self.send_json({"is_running": is_running, "config": current_config if is_running else None})
        elif self.path == '/api/logs':
            with log_lock:
                self.send_json(all_logs[-50:]) # Send last 50 logs
        elif self.path == '/api/interfaces':
            self.send_json({"interfaces": ["eth0", "wlan0"]}) # Mocked for safety
        else:
            self.send_error(404)

    def do_POST(self):
        global is_running, current_config
        if self.path == '/api/start':
            if is_running:
                self.send_json({"error": "Already running"}, 400)
                return
            
            content_len = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(content_len))
            
            is_running = True
            current_config = {"interface": data['interface'], "interval": data['interval_seconds']}
            
            t = threading.Thread(target=rotation_loop, args=(data['interface'], data['interval_seconds']))
            t.daemon = True
            t.start()
            
            self.send_json({"status": "started"})
            
        elif self.path == '/api/stop':
            is_running = False
            self.send_json({"status": "stopped"})
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
        pass # Silence HTTP logs

if __name__ == "__main__":
    try:
        print(">>> INITIALIZING SERVER...")
        print(">>> WARNING: You MUST run this with 'sudo' to change MAC addresses.")
        print(">>> If this window closes immediately, you have a syntax error or missing dependency.")
        
        server = HTTPServer(('0.0.0.0', 8000), Handler)
        print(">>> SERVER IS RUNNING. Waiting for commands...")
        server.serve_forever()
    except Exception as e:
        print(f"\n!!! CRITICAL FAILURE: {e}")
        print("!!! The script crashed before starting. Check the error above.")
        input("Press Enter to exit...") # Keep window open to read error