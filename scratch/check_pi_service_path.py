import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('192.168.0.240', username='admin', password='Veneno@2023', timeout=5)

stdin, stdout, stderr = client.exec_command('systemctl cat gate-tracker.service')
print("--- SERVICE DEFINITION ---")
print(stdout.read().decode())

stdin, stdout, stderr = client.exec_command("find /home/admin -name '*.jpg' 2>/dev/null")
print("--- ALL JPG ON PI ---")
print(stdout.read().decode().strip())

client.close()
