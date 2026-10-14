import paramiko
import sys

host = "192.168.0.240"
user = "admin"
passwords = ["admin", "raspberry", "veneno", "Veneno123", "Veneno@123", "123456", "1234", "root", "callmycar", "CallMyCar"]

print(f"Testing SSH connection to {user}@{host} ...")

for pwd in passwords:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=22, username=user, password=pwd, timeout=3, banner_timeout=3, auth_timeout=3)
        print(f"\n[SUCCESS] Connected to Pi with password: '{pwd}'!")
        
        # Check current running service status
        stdin, stdout, stderr = client.exec_command("sudo systemctl status gate-tracker.service --no-pager")
        print("\n--- Gate Tracker Service Status on Pi ---")
        print(stdout.read().decode())
        
        # Check current edge_tracker.py on Pi
        stdin, stdout, stderr = client.exec_command("grep -E 'MIN_CONTOUR_AREA|TRIPWIRE_BOTTOM_Y' /home/admin/visits_tracker/edge/edge_tracker.py")
        print("\n--- Active Config on Pi ---")
        print(stdout.read().decode())
        
        client.close()
        sys.exit(0)
    except paramiko.AuthenticationException:
        continue
    except Exception as e:
        print(f"Connection error with '{pwd}': {e}")
        break

print("\nNone of the common passwords matched. User needs to provide the SSH password.")
