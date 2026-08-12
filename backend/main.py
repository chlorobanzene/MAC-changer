import subprocess
import random
import os
import threading
import time
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# Global State
is_running = False
logs = []
lock = threading.Lock()

def log(msg):
    with lock:
        logs.append({"message": msg, "time": time.time()})
        if len(logs) > 50: logs.pop(0)
    print(f"[LOG] {msg}")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Serve frontend HTML (your existing code)
        if self.path in ['/', '/index.html']:
            # ... (keep your existing code here) ...
            return
        
        # API Endpoints
        if self.path == '/api/status':
            self.send_json({"is_running": is_running})
        elif self.path == '/api/logs':
            with lock:
                self.send_json(logs[-50:])
        elif self.path == '/api/interfaces':  # <-- ADD THIS BLOCK
            try:
                result = subprocess.run(["ip", "-o", "link", "show"], capture_output=True, text=True)
                interfaces = []
                for line in result.stdout.splitlines():
                    if "lo:" not in line:
                        parts = line.split()
                        if len(parts) > 1:
                            iface = parts[1].rstrip(':')
                            interfaces.append(iface)
                self.send_json({"interfaces": interfaces if interfaces else ["eth0", "wlan0"]})
            except:
                self.send_json({"interfaces": ["eth0", "wlan0"]})
        else:
            self.send_error(404)

    def do_POST(self):
        """THIS METHOD MUST EXIST OR YOU GET 501 ERROR"""
        global is_running
        
        print(f">>> POST request received: {self.path}")  # Debug print
        
        if self.path == '/api/start':
            # Read the JSON body
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len)
            
            try:
                data = json.loads(body.decode('utf-8')) if body else {}
            except:
                data = {}
            
            interface = data.get('interface', 'eth0')
            interval = data.get('interval_seconds', 60)
            
            if is_running:
                self.send_json({"error": "Already running"}, 400)
                return
            
            is_running = True
            log(f"Starting rotation on {interface}")
            
            # Start rotation in background thread
            def rotate():
                global is_running
                count = 0
                while is_running:
                    try:
                        # Generate MAC
                        mac = ":".join([f"{random.randint(0,255):02x}" for _ in range(6)])
                        mac = f"02{mac[2:]}"  # Ensure unicast bit
                        
                        log(f"Changing {interface} to {mac}")
                        
                        # Attempt to change MAC (requires root)
                        subprocess.run(["ip", "link", "set", interface, "down"], check=True, capture_output=True)
                        subprocess.run(["ip", "link", "set", interface, "address", mac], check=True, capture_output=True)
                        subprocess.run(["ip", "link", "set", interface, "up"], check=True, capture_output=True)
                        
                        log(f"Success: Changed to {mac}")
                        count += 1
                    except Exception as e:
                        log(f"ERROR: {str(e)}")
                        is_running = False
                        break
                    
                    # Sleep with interrupt check
                    for _ in range(interval * 10):
                        if not is_running: break
                        time.sleep(0.1)
                
                log("Rotation stopped")
            
            t = threading.Thread(target=rotate)
            t.daemon = True
            t.start()
            
            self.send_json({"status": "started", "interface": interface})
            
        elif self.path == '/api/stop':
            is_running = False
            log("Stop requested")
            self.send_json({"status": "stopped"})
        else:
            self.send_error(404)

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # Suppress default HTTP logging

if __name__ == "__main__":
    print(">>> Starting server on http://0.0.0.0:8000")
    print(">>> Open http://127.0.0.1:8000 in your browser")
    print(">>> WARNING: You MUST run this with 'sudo' for MAC changing to work")
    
    server = HTTPServer(('0.0.0.0', 8000), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n>>> Server stopped")
