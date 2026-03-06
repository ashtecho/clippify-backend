from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import bcrypt
import jwt
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

app = FastAPI(title="Clippify API")

# =========================
# CONFIG
# =========================

SECRET_KEY = "clippify-secret-key"
ALGORITHM = "HS256"

MAX_VIDEO_SIZE = 4 * 1024 * 1024 * 1024  # 4GB

security = HTTPBearer()

# =========================
# FOLDERS
# =========================

os.makedirs("uploads", exist_ok=True)
os.makedirs("audio", exist_ok=True)
os.makedirs("clips", exist_ok=True)

# =========================
# USER MODEL
# =========================

class User(BaseModel):
    email: EmailStr
    password: str

# =========================
# USER STORAGE
# =========================

USERS_FILE = "users.json"

def load_users():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            json.dump([], f)

    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

# =========================
# TOKEN SYSTEM
# =========================

def create_token(email: str):
    payload = {
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=24)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):

    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload

    except:
        raise HTTPException(status_code=401, detail="Invalid token")

# =========================
# ROUTES
# =========================

@app.get("/")
def home():
    return {"message": "Welcome to Clippify backend", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "healthy"}

# =========================
# SIGNUP
# =========================

@app.post("/signup")
def signup(user: User):

    users = load_users()

    for u in users:
        if u["email"] == user.email:
            raise HTTPException(status_code=400, detail="User already exists")

    hashed = bcrypt.hashpw(user.password.encode(), bcrypt.gensalt())

    users.append({
        "email": user.email,
        "password": hashed.decode()
    })

    save_users(users)

    return {"message": "User created securely"}

# =========================
# LOGIN
# =========================

@app.post("/login")
def login(user: User):

    users = load_users()

    for u in users:
        if u["email"] == user.email:

            if bcrypt.checkpw(user.password.encode(), u["password"].encode()):

                token = create_token(user.email)

                return {
                    "message": "Login successful",
                    "access_token": token
                }

            else:
                raise HTTPException(status_code=401, detail="Invalid password")

    raise HTTPException(status_code=404, detail="User not found")

# =========================
# DASHBOARD
# =========================

@app.get("/dashboard")
def dashboard(payload = Depends(verify_token)):

    return {
        "message": "Welcome",
        "user": payload["email"]
    }

# =========================
# SAFE VIDEO UPLOAD
# =========================

@app.post("/upload-video")
async def upload_video(
    file: UploadFile = File(...),
    payload = Depends(verify_token)
):

    allowed = [".mp4", ".mov", ".mkv"]

    if not any(file.filename.endswith(ext) for ext in allowed):
        raise HTTPException(status_code=400, detail="Unsupported video format")

    filepath = f"uploads/{file.filename}"

    size = 0

    with open(filepath, "wb") as buffer:

        while True:

            chunk = await file.read(1024 * 1024)  # 1MB chunk

            if not chunk:
                break

            size += len(chunk)

            if size > MAX_VIDEO_SIZE:
                buffer.close()
                os.remove(filepath)
                raise HTTPException(status_code=400, detail="File exceeds 4GB limit")

            buffer.write(chunk)

    return {
        "message": "Upload successful",
        "filename": file.filename,
        "size_mb": round(size / (1024*1024), 2),
        "saved_to": filepath,
        "status": "ready for processing"
    }
