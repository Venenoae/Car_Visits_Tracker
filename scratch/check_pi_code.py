import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.240', username='admin', password='Veneno@2023', timeout=5)

stdin, stdout, stderr = ssh.exec_command("grep -n -C 5 'Cross' /home/admin/edge_tracker.py")
print("Matches:")
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
