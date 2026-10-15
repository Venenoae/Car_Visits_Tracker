import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.240', username='admin', password='Veneno@2023', timeout=5)

sftp = ssh.open_sftp()
local_file = 'edge/edge_tracker.py'
remote_file = '/home/admin/edge_tracker.py'
print(f"Uploading {local_file} -> {remote_file}...")
sftp.put(local_file, remote_file)
sftp.close()
print("Upload complete!")

print("Restarting gate-tracker.service with sudo...")
stdin, stdout, stderr = ssh.exec_command('echo "Veneno@2023" | sudo -S systemctl restart gate-tracker.service')
print("STDOUT:", stdout.read().decode('utf-8', errors='replace'))
print("STDERR:", stderr.read().decode('utf-8', errors='replace'))

stdin, stdout, stderr = ssh.exec_command('ps aux | grep python3')
print("Running processes:")
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
