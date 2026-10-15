import sqlite3
import os

conn = sqlite3.connect('backend/car_visits_tracker.db')
c = conn.cursor()
c.execute("DELETE FROM visits WHERE plate_number LIKE 'UNREADABLE%'")
c.execute("DELETE FROM vehicles WHERE plate_number LIKE 'UNREADABLE%'")
conn.commit()

c.execute('SELECT count(*) FROM visits')
print('Remaining visits in DB:', c.fetchone()[0])
conn.close()

p = 'backend/uploads/ZoneA_Entry_20261015_190729_788325.jpg'
if os.path.exists(p):
    os.remove(p)
    print('Deleted false snapshot:', p)
