import os
import sys
import paramiko
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

load_dotenv()
host = os.getenv("RPI_HOST")
user = os.getenv("RPI_USER")
pwd = os.getenv("RPI_PASSWORD")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=8, banner_timeout=8, auth_timeout=8)
print(f"[connected] {user}@{host}")

cmds = [
    ("date", "date"),
    ("service status", "systemctl status gate-tracker.service --no-pager | head -15"),
    ("last 3 min log", "journalctl -u gate-tracker.service --since '3 min ago' --no-pager | tail -80"),
    ("cache dir (unsent)", "ls -la /home/admin/visits_tracker/edge/cache 2>&1 | tail -15"),
]
for title, cmd in cmds:
    _, out, err = client.exec_command(cmd)
    print(f"\n=== {title} ===")
    print(out.read().decode(errors="replace") + err.read().decode(errors="replace"))
client.close()
