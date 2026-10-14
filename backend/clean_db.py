import sqlite3

conn = sqlite3.connect(r'd:\Veneno\CallMyCar\Car_Visits_Tracker\backend\car_visits_tracker.db')
c = conn.cursor()
c.execute("DELETE FROM visits WHERE plate_number LIKE 'CAR-%'")
conn.commit()

c.execute("SELECT id, plate_number, zone, entry_timestamp, status, entry_image_url FROM visits ORDER BY id DESC")
rows = c.fetchall()
print(f"Total visits: {len(rows)}")
for r in rows:
    print(r)
conn.close()
