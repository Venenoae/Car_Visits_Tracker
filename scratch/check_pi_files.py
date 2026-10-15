import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.240', username='admin', password='Veneno@2023', timeout=5)

stdin, stdout, stderr = ssh.exec_command("find /home/admin -name '*.jpg'")
print("Images found:")
print(stdout.read().decode('utf-8', errors='replace'))

stdin, stdout, stderr = ssh.exec_command("grep -n 'imwrite' /home/admin/gate_tracker/edge_tracker.py")
print("imwrite lines:")
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
