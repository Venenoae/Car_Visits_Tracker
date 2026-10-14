import sqlite3

conn = sqlite3.connect(r'd:\Veneno\CallMyCar\Car_Visits_Tracker\backend\car_visits_tracker.db')
c = conn.cursor()
c.execute("PRAGMA table_info(visits)")
for col in c.fetchall():
    print(col)

c.execute("SELECT * FROM visits ORDER BY id DESC LIMIT 5")
for r in c.fetchall():
    print(r)
conn.close()
