import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Load environment variables
load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "car_visits_tracker")

# Connection URL & Engine initialization
USE_SQLITE = os.getenv("USE_SQLITE", "").lower() in ("true", "1", "yes")

def init_db_engine():
    if not USE_SQLITE:
        try:
            mysql_url = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?connect_timeout=2"
            test_engine = create_engine(
                mysql_url,
                pool_size=10,
                max_overflow=20,
                pool_recycle=3600,
                pool_pre_ping=True
            )
            with test_engine.connect() as conn:
                pass
            print(f"[DB] Connected to MySQL database ({MYSQL_DATABASE}) on {MYSQL_HOST}:{MYSQL_PORT}")
            return test_engine
        except Exception as e:
            print(f"[DB] MySQL connection to {MYSQL_HOST}:{MYSQL_PORT} unavailable ({e}). Falling back to local SQLite.")

    sqlite_file = os.path.join(os.path.dirname(__file__), "car_visits_tracker.db")
    print(f"[DB] Using local SQLite database: {sqlite_file}")
    return create_engine(
        f"sqlite:///{sqlite_file}",
        connect_args={"check_same_thread": False}
    )

engine = init_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- DATABASE MODELS ---

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Vehicle(Base):
    __tablename__ = "vehicles"

    plate_number = Column(String(20), primary_key=True, index=True)  # Uppercase, cleaned, no spaces
    color = Column(String(30))
    brand = Column(String(50))
    owner_name = Column(String(100))
    owner_phone = Column(String(20))
    owner_email = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    visits = relationship("Visit", back_populates="vehicle", cascade="all, delete-orphan")


class Visit(Base):
    __tablename__ = "visits"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    plate_number = Column(String(20), ForeignKey("vehicles.plate_number", onupdate="CASCADE"), nullable=False)
    zone = Column(String(10), nullable=False)  # 'Zone A' or 'Zone B'
    entry_timestamp = Column(DateTime, default=datetime.now)
    exit_timestamp = Column(DateTime, nullable=True)
    entry_image_url = Column(String(255))
    exit_image_url = Column(String(255))
    status = Column(String(20), default="Inside")  # 'Inside' or 'Completed'
    manually_created = Column(Boolean, default=False)
    manually_edited = Column(Boolean, default=False)

    # Relationships
    vehicle = relationship("Vehicle", back_populates="visits")
