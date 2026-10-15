import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.240', username='admin', password='Veneno@2023', timeout=5)

stdin, stdout, stderr = client.exec_command('journalctl -u gate-tracker.service -n 100 --no-pager')
output = stdout.read().decode('utf-8', errors='replace')
print(output.encode('ascii', errors='replace').decode('ascii'))
client.close()
