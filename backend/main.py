import subprocess
import random
import os
import threading
import time
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler

# Global State
is_running = False
logs = []
lock = threading.Lock()
current_config = {
    "interface": None, 
    "interval": 0, 
    "original_mac": None,
    "current_mac": None
}

def log(msg):
    with lock:
        logs.append({"message": msg, "time": time.time()})
        if len(logs) > 50: logs.pop(0)
    print(f"[LOG] {msg}")

def get_mac_address(interface):
    """Get the current MAC address of an interface."""
    try:
        result = subprocess.run(["ip", "link", "show", interface], capture_output=True, text=True)
        if result.returncode == 0:
            # Look for link/ether line
            match = re.search(r'link/ether\s+([0-9a-f:]{17})', result.stdout)
            if match:
                return match.group(1)
    except Exception as e:
        log(f"Error reading MAC: {e}")
    return "Unknown"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Serve frontend HTML
        if self.path in ['/', '/index.html']:
            try:
                backend_dir = os.path.dirname(os.path.abspath(__file__))
                project_dir = os.path.dirname(backend_dir)
                html_path = os.path.join(project_dir, 'frontend', 'index.html')
                
                with open(html_path, 'r') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(content.encode())
            except Exception as e:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(f"<h1>Error loading frontend</h1><p>{e}</p>".encode())
            return
        
        # API Endpoints
        if self.path == '/api/status':
            self.send_json({
                "is_running": is_running,
                "config": {
                    "interface": current_config.get("interface"),
                    "interval": current_config.get("interval"),
                    "original_mac": current_config.get("original_mac"),
                    "current_mac": get_mac_address(current_config.get("interface")) if current_config.get("interface") else None
                }
            })
        elif self.path == '/api/logs':
            with lock:
                self.send_json(logs[-50:])
        elif self.path == '/api/interfaces':
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
        elif self.path == '/api/mac':
            # Return current MAC info for the active interface
            iface = current_config.get("interface")
            if iface:
                current = get_mac_address(iface)
                self.send_json({
                    "interface": iface,
                    "original_mac": current_config.get("original_mac"),
                    "current_mac": current,
                    "is_running": is_running
                })
            else:
                self.send_json({"interface": None, "original_mac": None, "current_mac": None})
        else:
            self.send_error(404)

    def do_POST(self):
        global is_running, current_config
        
        if self.path == '/api/start':
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
            
            # Capture original MAC before starting
            original_mac = get_mac_address(interface)
            if original_mac == "Unknown":
                self.send_json({"error": f"Cannot read MAC of interface {interface}. Does it exist?"}, 400)
                return
            
            is_running = True
            current_config = {
                "interface": interface,
                "interval": interval,
                "original_mac": original_mac,
                "current_mac": original_mac
            }
            
            log(f"Starting rotation on {interface}")
            log(f"Original MAC: {original_mac}")
            
            def rotate():
                global is_running, current_config
                while is_running:
                    try:
                        # Generate random MAC
                        mac = ":".join([f"{random.randint(0,255):02x}" for _ in range(6)])
                        mac = f"02{mac[2:]}"  # Ensure unicast bit
                        
                        log(f"Changing {interface} to {mac}")
                        
                        subprocess.run(["ip", "link", "set", interface, "down"], check=True, capture_output=True)
                        subprocess.run(["ip", "link", "set", interface, "address", mac], check=True, capture_output=True)
                        subprocess.run(["ip", "link", "set", interface, "up"], check=True, capture_output=True)
                        
                        current_config["current_mac"] = mac
                        log(f"Success: Changed to {mac}")
                    except Exception as e:
                        log(f"ERROR: {str(e)}")
                        is_running = False
                        break
                    
                    for _ in range(interval * 10):
                        if not is_running: break
                        time.sleep(0.1)
                
                log("Rotation stopped")
            
            t = threading.Thread(target=rotate)
            t.daemon = True
            t.start()
            
            self.send_json({
                "status": "started", 
                "interface": interface,
                "original_mac": original_mac
            })
            
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
        pass

if __name__ == "__main__":
    print(">>> Server running on http://0.0.0.0:8000")
    print(">>> Open http://127.0.0.1:8000 in your browser")
    server = HTTPServer(('0.0.0.0', 8000), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n>>> Server stopped")
