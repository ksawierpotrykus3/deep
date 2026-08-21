import subprocess
import os
import psutil

print("Checking processes...")
killed = 0
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = proc.info.get('cmdline') or []
        cmd_str = ' '.join(cmdline)
        if 'gemini_profile' in cmd_str:
            print(f"Found running profile process PID {proc.pid}: {proc.info.get('name')}")
            proc.kill()
            killed += 1
    except Exception:
        pass

print(f"Killed {killed} leftover processes holding gemini_profile lock.")
