import subprocess
import random
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MacChangerError(Exception):
    pass

def generate_random_mac():
    """Generate a random MAC address with valid unicast bits."""
    # First byte must be even (unicast) and not 00
    first_byte = random.randint(1, 254) & 0xFE
    if first_byte == 0:
        first_byte = 2
    
    mac = [first_byte]
    for _ in range(5):
        mac.append(random.randint(0, 255))
    
    return ":".join(f"{b:02x}" for b in mac)

def get_interface_list():
    """List available network interfaces (Linux only)."""
    try:
        # Using ip command which is standard on modern Linux
        result = subprocess.run(["ip", "link"], capture_output=True, text=True, check=True)
        lines = result.stdout.split('\n')
        interfaces = []
        current_name = None
        
        for line in lines:
            if ": " in line and "@" not in line.split(":")[0].strip():
                # This is a main interface line
                parts = line.split(": ")
                if len(parts) >= 2:
                    idx_part = parts[0].strip()
                    if idx_part.isdigit():
                        name_part = parts[1].split("@")[0]
                        if name_part != "lo": # Skip loopback
                            interfaces.append(name_part)
        return interfaces
    except Exception as e:
        logger.error(f"Failed to list interfaces: {e}")
        return []

def change_mac_address(interface: str, mac_address: str):
    """
    Change the MAC address of a specific interface.
    Requires root privileges.
    """
    if os.name == 'nt':
        raise MacChangerError("Windows support requires different commands (netsh). This script is for Linux.")
    
    try:
        # Bring interface down
        subprocess.run(["ip", "link", "set", interface, "down"], check=True, capture_output=True)
        
        # Change MAC
        result = subprocess.run(
            ["ip", "link", "set", interface, "address", mac_address], 
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            raise MacChangerError(f"Failed to set MAC: {result.stderr}")
        
        # Bring interface up
        subprocess.run(["ip", "link", "set", interface, "up"], check=True, capture_output=True)
        
        logger.info(f"Successfully changed {interface} to {mac_address}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"System command failed: {e}")
        raise MacChangerError(f"Permission denied or interface error. Ensure you run as root. {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise MacChangerError(str(e))

def restore_original_mac(interface: str, original_mac: str):
    """Attempt to restore the original MAC (if hardware permits)."""
    try:
        subprocess.run(["ip", "link", "set", interface, "down"], check=True, capture_output=True)
        subprocess.run(["ip", "link", "set", interface, "address", original_mac], check=True, capture_output=True)
        subprocess.run(["ip", "link", "set", interface, "up"], check=True, capture_output=True)
        logger.info(f"Restored original MAC for {interface}")
    except Exception as e:
        logger.error(f"Could not restore original MAC: {e}")