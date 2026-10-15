import paramiko

PI_HOST = "192.168.0.240"
PI_USER = "admin"
PI_PASS = "Veneno@2023"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=5)

# Find cache directories
stdin, stdout, stderr = client.exec_command("find /home/admin -type d -name 'cache' 2>/dev/null")
cache_dirs = stdout.read().decode().strip().split('\n')
print(f"Found cache directories on Pi: {cache_dirs}")

for cdir in cache_dirs:
    if cdir.strip():
        stdin, stdout, stderr = client.exec_command(f"ls -1 {cdir}/*.jpg 2>/dev/null | wc -l")
        count = stdout.read().decode().strip()
        print(f"Directory {cdir} has {count} .jpg files.")
        if int(count) > 0:
            stdin, stdout, stderr = client.exec_command(f"rm -f {cdir}/*.jpg")
            print(f"Deleted .jpg files in {cdir}.")

# Also check /tmp for any snapshot files
stdin, stdout, stderr = client.exec_command("rm -f /tmp/*.jpg /tmp/*.png 2>/dev/null; echo 'Tmp cleaned.'")
print(stdout.read().decode().strip())

client.close()
print("Pi cache cleanup complete!")
