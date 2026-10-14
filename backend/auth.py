import os
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.orm import Session

from database import get_db, User

# Load environment variables
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "9a4fdc2f9d8a5c328eef62a98f45a0d312bc8a6190dbad7dce3e4b09c5302f3c")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# Helper to automatically create an initial admin user if the table is empty
def init_admin_user(db: Session):
    admin_exists = db.query(User).first()
    if not admin_exists:
        # Default credentials for local testing
        default_username = "admin"
        default_password = "adminpassword123"
        hashed_password = get_password_hash(default_password)
        
        new_admin = User(
            username=default_username,
            password_hash=hashed_password
        )
        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)
        print(f"\n[INFO] Initialized default admin user:")
        print(f"       Username: {default_username}")
        print(f"       Password: {default_password}")
        print(f"       Please change this password after logging in!\n")
