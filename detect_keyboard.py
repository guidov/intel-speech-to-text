#!/usr/bin/env python3
"""Helper script to detect keyboard input devices.

This script can be used to find your keyboard device path instead of manually using evtest.
Note: This script requires root privileges to access input devices, similar to the key listener.
Run with: sudo python detect_keyboard.py
"""

from pathlib import Path
import sys

try:
    import evdev
except ImportError:
    print("evdev module not found. Install with: pip install evdev")
    sys.exit(1)


def detect_keyboard_devices(trigger_keycode: str = "KEY_RIGHTCTRL"):
    """Detect keyboard devices on the system."""
    print(f"Looking for devices with trigger key: {trigger_keycode}")
    print("Available input devices:")
    print("-" * 50)
    
    input_dir = Path("/dev/input")
    event_devices = [f for f in input_dir.glob("event*")]
    event_devices.sort(key=lambda x: int(x.name.replace("event", "")))
    
    found_devices = []
    
    for device_path in event_devices:
        try:
            device = evdev.InputDevice(str(device_path))
            
            # Check if this device supports the trigger key
            has_trigger_key = False
            device_type = "Other"
            
            if hasattr(device, 'cap') and evdev.ecodes.EV_KEY in device.cap:
                keys = device.cap[evdev.ecodes.EV_KEY]
                trigger_evcode = evdev.ecodes.ecodes.get(trigger_keycode)
                
                if trigger_evcode in keys:
                    has_trigger_key = True
                    device_type = "Keyboard (has trigger key)"
                elif any(keyword in device.name.lower() for keyword in ['keyboard', 'key', 'kbd']):
                    device_type = "Keyboard (by name)"
                else:
                    device_type = "Input Device"
            
            print(f"Device: {device_path}")
            print(f"  Name: {device.name}")
            print(f"  Type: {device_type}")
            if has_trigger_key:
                print(f"  ✓ Has trigger key: {trigger_keycode}")
            print()
            
            if has_trigger_key or device_type.startswith("Keyboard"):
                found_devices.append(str(device.path))
                
        except (PermissionError, OSError):
            print(f"Device: {device_path}")
            print(f"  ERROR: Cannot access device (Permission denied or device not available)")
            print()
        except Exception as e:
            print(f"Device: {device_path}")
            print(f"  ERROR: {str(e)}")
            print()
    
    if found_devices:
        print(f"Potential keyboard devices found: {found_devices}")
        print(f"Recommended: Use the one with trigger key ({trigger_keycode})")
    else:
        print("No keyboard devices found!")


if __name__ == "__main__":
    trigger_key = "KEY_RIGHTCTRL"  # Default, can be changed
    
    if len(sys.argv) > 1:
        trigger_key = sys.argv[1]
        
    detect_keyboard_devices(trigger_key)