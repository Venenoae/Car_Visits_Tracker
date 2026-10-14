import sqlite3

conn = sqlite3.connect(r'd:\Veneno\CallMyCar\Car_Visits_Tracker\backend\car_visits_tracker.db')
c = conn.cursor()
c.execute("SELECT id, plate_number, zone, entry_timestamp, status, entry_image_url FROM visits WHERE plate_number = '49949'")
print("Visit:", c.fetchall())

c.execute("SELECT plate_number, color, brand FROM vehicles WHERE plate_number = '49949'")
print("Vehicle:", c.fetchall())
conn.close()
