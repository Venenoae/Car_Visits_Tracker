import os
import re
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from database import Visit

load_dotenv()

UPLOADS_DIR = os.getenv("UPLOADS_DIR", "uploads")
IMAGE_RETENTION_DAYS = int(os.getenv("IMAGE_RETENTION_DAYS", "2"))


def get_uploads_directory() -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    uploads_dir = os.path.join(base_dir, UPLOADS_DIR)
    os.makedirs(uploads_dir, exist_ok=True)
    return uploads_dir


def get_file_timestamp(entry: os.DirEntry) -> float:
    """
    Extracts the capture timestamp from the filename if possible
    (e.g., ZoneA_Entry_20261014_192012_... or ZoneA_Exit_20260926_172759.jpg),
    falling back to file modification time (mtime).
    """
    match = re.search(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})', entry.name)
    if match:
        try:
            year, month, day, hour, minute, second = map(int, match.groups())
            dt = datetime(year, month, day, hour, minute, second)
            return dt.timestamp()
        except ValueError:
            pass
    try:
        return entry.stat().st_mtime
    except OSError:
        return time.time()


def get_storage_stats(retention_days: int = None) -> dict:
    """
    Returns statistics about image storage and files eligible for deletion.
    """
    if retention_days is None:
        retention_days = IMAGE_RETENTION_DAYS

    uploads_dir = get_uploads_directory()
    cutoff_timestamp = time.time() - (retention_days * 86400)

    total_files = 0
    total_bytes = 0
    old_files = 0
    old_bytes = 0

    if os.path.exists(uploads_dir):
        for entry in os.scandir(uploads_dir):
            if entry.is_file():
                total_files += 1
                try:
                    size = entry.stat().st_size
                    total_bytes += size
                    file_ts = get_file_timestamp(entry)
                    if file_ts < cutoff_timestamp:
                        old_files += 1
                        old_bytes += size
                except OSError:
                    continue

    return {
        "total_files": total_files,
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "old_files": old_files,
        "old_size_mb": round(old_bytes / (1024 * 1024), 2),
        "retention_days": retention_days,
        "cutoff_date": (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")
    }


def cleanup_old_images(db: Session, retention_days: int = None) -> dict:
    """
    Deletes snapshot image files older than retention_days (default 2 days / 48 hours).
    Updates corresponding Visit records in the database so entry_image_url and exit_image_url
    become NULL, keeping the visit and vehicle records completely intact.
    """
    if retention_days is None:
        retention_days = IMAGE_RETENTION_DAYS

    uploads_dir = get_uploads_directory()
    cutoff_timestamp = time.time() - (retention_days * 86400)

    deleted_files = 0
    freed_bytes = 0
    deleted_filenames = []

    if os.path.exists(uploads_dir):
        for entry in os.scandir(uploads_dir):
            if entry.is_file():
                try:
                    file_ts = get_file_timestamp(entry)
                    if file_ts < cutoff_timestamp:
                        size = entry.stat().st_size
                        os.remove(entry.path)
                        deleted_files += 1
                        freed_bytes += size
                        deleted_filenames.append(entry.name)
                except OSError as e:
                    print(f"[Cleanup] Error deleting file {entry.name}: {e}")

    # Nullify database image references for deleted files
    updated_records = 0
    if deleted_filenames:
        try:
            chunk_size = 100
            for i in range(0, len(deleted_filenames), chunk_size):
                chunk = deleted_filenames[i:i + chunk_size]
                for fn in chunk:
                    img_path_pattern = f"%{fn}%"
                    res_entry = db.query(Visit).filter(
                        Visit.entry_image_url.like(img_path_pattern)
                    ).update({Visit.entry_image_url: None}, synchronize_session=False)

                    res_exit = db.query(Visit).filter(
                        Visit.exit_image_url.like(img_path_pattern)
                    ).update({Visit.exit_image_url: None}, synchronize_session=False)

                    updated_records += (res_entry + res_exit)

            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[Cleanup] Error updating database records: {e}")

    freed_mb = round(freed_bytes / (1024 * 1024), 2)
    print(f"[Maintenance] Cleaned {deleted_files} old images ({freed_mb} MB freed). Updated {updated_records} DB visit image pointers.")

    return {
        "success": True,
        "deleted_count": deleted_files,
        "freed_mb": freed_mb,
        "db_records_updated": updated_records,
        "retention_days": retention_days
    }
