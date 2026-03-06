import os
import json
import jwt
import bcrypt
import shutil
import ffmpeg
from datetime import datetime, timedelta

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from faster_whisper import WhisperModel

# -----------------------------
# CONFIG
# -----------------------------

SECRET_KEY = "clippify_secret_key"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

UPLOAD_FOLDER = "uploads"
AUDIO_FOLDER = "audio"
USERS_DB = "users.json"

MAX_VIDEO_SIZE = 4 * 1024 * 1024 * 1024  # 4GB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

# -----------------------------
# FASTAPI
# -----------------------------

app = FastAPI(
    title="Clippify API",
    version="0.1.0"
)

security = HTTPBearer()

# -----------------------------
# WHISPER MODEL
# -----------------------------

model = WhisperModel(
    "tiny",
    compute_type="int8"
)

# -----------------------------
# USER MODEL
# -----------------------------

class User(BaseModel):
    email: EmailStr
    password: str


# -----------------------------
# DATABASE HELPERS
# -----------------------------

def load_users():
    if not os.path.exists(USERS_DB):
        with open(USERS_DB, "w") as f:
            json.dump([], f)

    with open(USERS_DB, "r") as f:
        return json.load(f)


def save_users(users):
    with open(USERS_DB, "w") as f:
        json.dump(users, f)


# -----------------------------
# AUTH HELPERS
# -----------------------------

def create_token(email):

    payload = {
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):

    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except:
        raise HTTPException(status_code=401, detail="Invalid token")


# -----------------------------
# ROUTES
# -----------------------------

@app.get("/")
def home():
    return {
        "message": "Welcome to Clippify API",
        "docs": "/docs"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "time": datetime.utcnow()
    }


# -----------------------------
# SIGNUP
# -----------------------------

@app.post("/signup")
def signup(user: User):

    users = load_users()

    for u in users:
        if u["email"] == user.email:
            raise HTTPException(status_code=400, detail="Email already exists")

    hashed_pw = bcrypt.hashpw(user.password.encode(), bcrypt.gensalt()).decode()

    users.append({
        "email": user.email,
        "password": hashed_pw
    })

    save_users(users)

    return {"message": "User created successfully"}


# -----------------------------
# LOGIN
# -----------------------------

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

            raise HTTPException(status_code=401, detail="Invalid password")

    raise HTTPException(status_code=404, detail="User not found")


# -----------------------------
# DASHBOARD
# -----------------------------

@app.get("/dashboard")
def dashboard(payload=Depends(verify_token)):

    return {
        "message": "Welcome",
        "user": payload["email"]
    }


# -----------------------------
# VIDEO UPLOAD
# -----------------------------

@app.post("/upload-video")
async def upload_video(
    file: UploadFile = File(...),
    payload=Depends(verify_token)
):

    file_location = f"{UPLOAD_FOLDER}/{file.filename}"

    size = 0

    with open(file_location, "wb") as buffer:

        while True:
            chunk = await file.read(1024 * 1024)

            if not chunk:
                break

            size += len(chunk)

            if size > MAX_VIDEO_SIZE:
                os.remove(file_location)
                raise HTTPException(status_code=413, detail="File too large")

            buffer.write(chunk)

    # -----------------------------
    # AUDIO EXTRACTION
    # -----------------------------

    audio_path = f"{AUDIO_FOLDER}/{file.filename}.wav"

    try:

        (
            ffmpeg
            .input(file_location)
            .output(audio_path, ac=1, ar="16000")
            .run(overwrite_output=True)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail="FFmpeg processing failed")

    # -----------------------------
    # TRANSCRIPTION
    # -----------------------------

    try:

        segments, info = model.transcribe(audio_path)

        transcript = ""

        for segment in segments:
            transcript += segment.text + " "

    except Exception as e:
        raise HTTPException(status_code=500, detail="Whisper transcription failed")

    return {

        "message": "Upload successful",

        "user": payload["email"],

        "video_saved": file_location,

        "audio_file": audio_path,

        "transcript_preview": transcript[:500]

    }
