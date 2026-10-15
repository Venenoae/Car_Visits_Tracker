import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.240', username='admin', password='Veneno@2023', timeout=5)

sftp = client.open_sftp()
sftp.put('edge/edge_tracker.py', '/home/admin/edge_tracker.py')
sftp.close()

stdin, stdout, stderr = client.exec_command('sudo systemctl restart gate-tracker.service')
stdout.channel.recv_exit_status()

stdin, stdout, stderr = client.exec_command("grep -E 'DETECTION_(X|Y)_(MIN|MAX)' /home/admin/edge_tracker.py")
print("--- PI ACTIVE CALIBRATION ---")
print(stdout.read().decode())

stdin, stdout, stderr = client.exec_command('systemctl is-active gate-tracker.service')
print('Pi service status:', stdout.read().decode().strip())

client.close()
