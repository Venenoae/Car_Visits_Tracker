import sqlite3

conn = sqlite3.connect('backend/car_visits_tracker.db')
c = conn.cursor()

# Update visit 2 to an active Inside visit
c.execute("""
    UPDATE visits
    SET status = 'Inside',
        entry_timestamp = '2026-10-15 19:31:37',
        entry_image_url = '/static/uploads/ZoneA_Exit_20261015_193137_430895.jpg',
        exit_timestamp = NULL,
        exit_image_url = NULL
    WHERE id = 2
""")

# Update vehicle to Black Nissan
c.execute("""
    INSERT OR REPLACE INTO vehicles (plate_number, color, brand, created_at, updated_at)
    VALUES ('7238', 'Black', 'Nissan', datetime('now'), datetime('now'))
""")

conn.commit()

c.execute("SELECT * FROM visits WHERE id = 2")
print("Updated Visit #2:", c.fetchone())

c.execute("SELECT * FROM vehicles WHERE plate_number = '7238'")
print("Updated Vehicle:", c.fetchone())

conn.close()
