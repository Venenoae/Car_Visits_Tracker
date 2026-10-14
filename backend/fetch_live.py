import requests
import sys

try:
    print("Connecting to Pi at http://192.168.0.240:8080/snapshot ...")
    r = requests.get('http://192.168.0.240:8080/snapshot', timeout=6)
    if r.status_code == 200:
        with open('d:/Veneno/CallMyCar/Car_Visits_Tracker/backend/uploads/live_preview.jpg', 'wb') as f:
            f.write(r.content)
        print(f"SUCCESS: Snapshot saved ({len(r.content)} bytes)")
    else:
        print(f"HTTP Status: {r.status_code} - latest_annotated_frame might be None yet!")
except Exception as e:
    print(f"ERROR: {e}")
