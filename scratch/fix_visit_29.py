import sqlite3

conn = sqlite3.connect('backend/car_visits_tracker.db')
c = conn.cursor()

# Update visit 29
c.execute("UPDATE visits SET plate_number = '17 21486' WHERE id = 29")

# Delete old broken plate vehicle record
c.execute("DELETE FROM vehicles WHERE plate_number = '17 216'")

# Insert or replace correct vehicle record
c.execute("""
    INSERT OR REPLACE INTO vehicles (plate_number, color, brand, created_at, updated_at)
    VALUES ('17 21486', 'White', 'Toyota', datetime('now'), datetime('now'))
""")

conn.commit()

c.execute("SELECT * FROM visits WHERE id = 29")
print('Visit 29:', c.fetchone())

c.execute("SELECT * FROM vehicles WHERE plate_number = '17 21486'")
print('Vehicle:', c.fetchone())
conn.close()
