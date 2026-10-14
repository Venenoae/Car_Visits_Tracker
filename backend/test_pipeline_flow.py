import requests
import time

url = "http://127.0.0.1:8000/api/capture"
img_path = r"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\uploads\ZoneA_Entry_20260924_173101_775402.jpg"

with open(img_path, "rb") as f:
    files = {"file": ("test_outdoor_car.jpg", f, "image/jpeg")}
    data = {"zone": "Zone A", "direction": "Entry"}
    print("Sending test capture to backend...")
    res = requests.post(url, data=data, files=files)
    print("Response status:", res.status_code)
    print("Response JSON:", res.json())

# Wait 5 seconds for background task to process AI and DB
print("Waiting 5s for AI pipeline background task...")
time.sleep(5)

import sqlite3
conn = sqlite3.connect(r"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\car_visits_tracker.db")
c = conn.cursor()
c.execute("SELECT id, plate_number, zone, entry_timestamp, status, entry_image_url FROM visits ORDER BY id DESC LIMIT 3")
print("Latest visits in DB:")
for row in c.fetchall():
    print(row)
conn.close()
