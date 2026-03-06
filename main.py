import os
import json
import jwt
import bcrypt
import subprocess
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
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

MAX_VIDEO_SIZE = 4 * 1024 * 1024 * 1024

# -------------------------
# CREATE DIRECTORIES
# -------------------------

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)
os.makedirs(CLIPS_FOLDER, exist_ok=True)

# -------------------------
# FASTAPI
# -------------------------

app = FastAPI(title="Clippify API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

# -------------------------
# WHISPER MODEL
# -------------------------

model = WhisperModel(
    "tiny",
    compute_type="int8",
    cpu_threads=4
)

# -------------------------
# THREAD POOL
# -------------------------

executor = ThreadPoolExecutor(max_workers=4)

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
# AUTH
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
# ROUTES
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
# FAST AUDIO EXTRACTION
# -------------------------

def extract_audio(video_path, audio_path):

    subprocess.run([
        "ffmpeg",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-y",
        audio_path
    ])

# -------------------------
# CLIP CUTTING (FAST SEEK)
# -------------------------

def cut_clip(video, start, end, output):

    subprocess.run([
        "ffmpeg",
        "-ss", str(start),
        "-to", str(end),
        "-i", video,
        "-c", "copy",
        "-y",
        output
    ])

# -------------------------
# PROCESS VIDEO
# -------------------------

def process_video(video_path):

    filename = os.path.basename(video_path)

    audio_path = f"{AUDIO_FOLDER}/{filename}.wav"

    extract_audio(video_path, audio_path)

    segments, info = model.transcribe(audio_path)

    timestamps = []

    for seg in segments:

        if len(seg.text.split()) > 6:

            timestamps.append((seg.start, seg.end))

    clips = []

    for i, (start, end) in enumerate(timestamps[:5]):

        clip_path = f"{CLIPS_FOLDER}/clip_{i}.mp4"

        cut_clip(video_path, start, end, clip_path)

        clips.append(clip_path)

    os.remove(video_path)
    os.remove(audio_path)

    return clips

# -------------------------
# VIDEO UPLOAD
# -------------------------

@app.post("/upload-video")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    payload=Depends(verify_token)
):

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

    background_tasks.add_task(process_video, video_path)

    return {
        "message": "Upload successful. Processing started."
    }
