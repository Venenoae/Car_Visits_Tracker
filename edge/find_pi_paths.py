import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect("192.168.0.240", port=22, username="admin", password="Veneno@2023", timeout=8)

stdin, stdout, stderr = client.exec_command("find /home/admin -maxdepth 3 -type f -name '*.py'")
print("--- Found Python files on Pi ---")
print(stdout.read().decode('utf-8', errors='replace'))

stdin, stdout, stderr = client.exec_command("cat /etc/systemd/system/gate-tracker.service 2>/dev/null || systemctl cat gate-tracker.service")
print("--- gate-tracker.service definition ---")
print(stdout.read().decode('utf-8', errors='replace'))

client.close()
