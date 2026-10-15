import sqlite3
import shutil
import os

db_path = r'd:\Veneno\CallMyCar\Car_Visits_Tracker\backend\car_visits_tracker.db'
backup_path = r'd:\Veneno\CallMyCar\Car_Visits_Tracker\backend\car_visits_tracker.db.pre_clear_backup'

# Create backup
shutil.copy2(db_path, backup_path)
print(f"Created backup at: {backup_path}")

conn = sqlite3.connect(db_path)
c = conn.cursor()

# Get before counts
c.execute("SELECT count(*) FROM visits")
visits_before = c.fetchone()[0]

c.execute("SELECT count(*) FROM vehicles")
vehicles_before = c.fetchone()[0]

c.execute("SELECT count(*) FROM users")
users_before = c.fetchone()[0]

print(f"Before clearing: {visits_before} visits, {vehicles_before} vehicles, {users_before} users.")

# Delete all visits and vehicles
c.execute("DELETE FROM visits")
c.execute("DELETE FROM vehicles")

# Reset auto-increment counter so next visit starts at #1
try:
    c.execute("DELETE FROM sqlite_sequence WHERE name IN ('visits', 'vehicles')")
except sqlite3.OperationalError:
    pass

conn.commit()

# Verify after counts
c.execute("SELECT count(*) FROM visits")
visits_after = c.fetchone()[0]

c.execute("SELECT count(*) FROM vehicles")
vehicles_after = c.fetchone()[0]

c.execute("SELECT count(*) FROM users")
users_after = c.fetchone()[0]

print(f"After clearing: {visits_after} visits, {vehicles_after} vehicles, {users_after} users.")
conn.close()
