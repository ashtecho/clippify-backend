import os
import json
import jwt
import bcrypt
import ffmpeg
from datetime import datetime, timedelta

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from faster_whisper import WhisperModel

# -------------------------
# CONFIG
# -------------------------

SECRET_KEY = "clippify_secret"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

UPLOAD_FOLDER = "uploads"
AUDIO_FOLDER = "audio"
CLIPS_FOLDER = "clips"

USERS_DB = "users.json"

MAX_VIDEO_SIZE = 4 * 1024 * 1024 * 1024  # 4GB


# -------------------------
# CREATE FOLDERS
# -------------------------

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)
os.makedirs(CLIPS_FOLDER, exist_ok=True)

# -------------------------
# FASTAPI
# -------------------------

app = FastAPI(title="Clippify API")

security = HTTPBearer()

# -------------------------
# LOAD WHISPER MODEL
# -------------------------

model = WhisperModel("tiny", compute_type="int8")

# -------------------------
# USER MODEL
# -------------------------

class User(BaseModel):
    email: EmailStr
    password: str


# -------------------------
# DATABASE
# -------------------------

def load_users():

    if not os.path.exists(USERS_DB):
        with open(USERS_DB, "w") as f:
            json.dump([], f)

    with open(USERS_DB, "r") as f:
        return json.load(f)


def save_users(users):

    with open(USERS_DB, "w") as f:
        json.dump(users, f)


# -------------------------
# AUTH FUNCTIONS
# -------------------------

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


# -------------------------
# BASIC ROUTES
# -------------------------

@app.get("/")
def home():
    return {"message": "Clippify backend running", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "healthy", "time": datetime.utcnow()}


# -------------------------
# SIGNUP
# -------------------------

@app.post("/signup")
def signup(user: User):

    users = load_users()

    for u in users:
        if u["email"] == user.email:
            raise HTTPException(status_code=400, detail="User already exists")

    hashed_pw = bcrypt.hashpw(user.password.encode(), bcrypt.gensalt()).decode()

    users.append({
        "email": user.email,
        "password": hashed_pw
    })

    save_users(users)

    return {"message": "User created successfully"}


# -------------------------
# LOGIN
# -------------------------

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


# -------------------------
# DASHBOARD
# -------------------------

@app.get("/dashboard")
def dashboard(payload=Depends(verify_token)):

    return {
        "message": "Welcome",
        "user": payload["email"]
    }


# -------------------------
# VIDEO UPLOAD
# -------------------------

@app.post("/upload-video")
async def upload_video(file: UploadFile = File(...), payload=Depends(verify_token)):

    video_path = f"{UPLOAD_FOLDER}/{file.filename}"

    size = 0

    with open(video_path, "wb") as buffer:

        while True:

            chunk = await file.read(1024 * 1024)

            if not chunk:
                break

            size += len(chunk)

            if size > MAX_VIDEO_SIZE:
                os.remove(video_path)
                raise HTTPException(status_code=413, detail="File too large")

            buffer.write(chunk)

    # -------------------------
    # EXTRACT AUDIO
    # -------------------------

    audio_path = f"{AUDIO_FOLDER}/{file.filename}.wav"

    ffmpeg.input(video_path).output(
        audio_path,
        ac=1,
        ar="16000"
    ).run(overwrite_output=True)

    # -------------------------
    # TRANSCRIBE
    # -------------------------

    segments, info = model.transcribe(audio_path)

    timestamps = []

    for s in segments:

        timestamps.append({
            "start": s.start,
            "end": s.end,
            "text": s.text
        })

    # -------------------------
    # GENERATE CLIPS
    # -------------------------

    clip_paths = []

    for i, seg in enumerate(timestamps[:5]):

        start = seg["start"]
        end = seg["end"]

        clip_path = f"{CLIPS_FOLDER}/clip_{i}.mp4"

        ffmpeg.input(video_path, ss=start, to=end).output(
            clip_path
        ).run(overwrite_output=True)

        clip_paths.append(clip_path)

    # -------------------------
    # CLEANUP
    # -------------------------

    os.remove(video_path)
    os.remove(audio_path)

    return {

        "message": "Processing complete",

        "clips": clip_paths
    }
