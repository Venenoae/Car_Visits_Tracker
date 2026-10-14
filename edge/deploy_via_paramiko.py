import os
import sys
import paramiko
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

HOST = "192.168.0.240"
USER = "admin"
PASSWORD = sys.argv[1] if len(sys.argv) > 1 else "Veneno@2023"

local_script = os.path.join(os.path.dirname(__file__), "edge_tracker.py")
remote_path = "/home/admin/edge_tracker.py"

print(f"Connecting to {USER}@{HOST} ...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(HOST, port=22, username=USER, password=PASSWORD, timeout=8)
    print("[SUCCESS] SSH Connected successfully!")

    # 1. SFTP Upload
    print(f"Uploading {local_script} -> {remote_path} ...")
    sftp = client.open_sftp()
    sftp.put(local_script, remote_path)
    sftp.close()
    print("[SUCCESS] File upload complete!")

    # 2. Restart gate-tracker.service
    print("Restarting gate-tracker.service on Raspberry Pi ...")
    stdin, stdout, stderr = client.exec_command(f"echo '{PASSWORD}' | sudo -S systemctl restart gate-tracker.service")
    exit_status = stdout.channel.recv_exit_status()
    print(f"Service restart exit status: {exit_status}")

    # 3. Check status
    stdin, stdout, stderr = client.exec_command("sudo systemctl status gate-tracker.service --no-pager")
    status_out = stdout.read().decode('utf-8', errors='replace')
    print("\n--- Gate Tracker Status ---")
    print(status_out)

    # 4. Verify config active on Pi
    stdin, stdout, stderr = client.exec_command(f"grep -E 'TRIPWIRE_TOP_Y|TRIPWIRE_BOTTOM_Y|MIN_CONTOUR_AREA|DETECTION_Y_MAX' {remote_path}")
    print("\n--- Active Config on Pi ---")
    print(stdout.read().decode('utf-8', errors='replace'))

    client.close()
    print("[COMPLETE] DEPLOYMENT TO RASPBERRY PI FINISHED!")

except Exception as e:
    print(f"[ERROR] Deployment failed: {e}")
    sys.exit(1)
