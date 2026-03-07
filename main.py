import os
import time
import subprocess
from typing import List

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import jwt
import yt_dlp

# -------------------------
# CONFIG
# -------------------------

SECRET_KEY = "clippify_super_secure_secret_key_2026_ai_video_platform"
ALGORITHM = "HS256"

DOWNLOAD_DIR = "downloads"
AUDIO_DIR = "audio"
CLIPS_DIR = "clips"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

# -------------------------
# APP
# -------------------------

app = FastAPI(title="Clippify API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/clips", StaticFiles(directory="clips"), name="clips")

# -------------------------
# AUTH
# -------------------------

security = HTTPBearer()
users_db = {}

class User(BaseModel):
    email: str
    password: str

class YoutubeRequest(BaseModel):
    url: str

def create_token(email: str):
    payload = {"email": email, "exp": int(time.time()) + 86400}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["email"]
    except:
        raise HTTPException(status_code=401, detail="Invalid token")

# -------------------------
# ROUTES
# -------------------------

@app.get("/")
def home():
    return {"message": "Clippify backend running"}

@app.get("/health")
def health():
    return {"status": "ok"}

# -------------------------
# AUTH ROUTES
# -------------------------

@app.post("/signup")
def signup(user: User):

    if user.email in users_db:
        raise HTTPException(status_code=400, detail="User already exists")

    users_db[user.email] = user.password

    return {"message": "Signup successful"}

@app.post("/login")
def login(user: User):

    if users_db.get(user.email) != user.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user.email)

    return {"access_token": token}

# -------------------------
# YOUTUBE DOWNLOAD
# -------------------------

def download_youtube(url: str):

    filename = f"{DOWNLOAD_DIR}/video_{int(time.time()*1000)}.mp4"

    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": filename,
        "noplaylist": True,
        "quiet": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return filename

# -------------------------
# AUDIO EXTRACTION
# -------------------------

def extract_audio(video_path: str):

    audio_path = f"{AUDIO_DIR}/{os.path.basename(video_path)}.wav"

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-ar", "16000",
        "-ac", "1",
        "-vn",
        audio_path,
        "-y"
    ]

    subprocess.run(cmd, check=True, timeout=120)

    return audio_path

# -------------------------
# CLIP GENERATION
# -------------------------

def generate_clips(video_path: str):

    clips = []

    clip_length = 35
    start = 0

    for i in range(3):

        clip_path = f"{CLIPS_DIR}/clip_{int(time.time())}_{i}.mp4"

        cmd = [
            "ffmpeg",
            "-ss", str(start),
            "-t", str(clip_length),
            "-i", video_path,

            "-vf",
            "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",

            "-preset", "ultrafast",
            "-threads", "2",

            "-c:v", "libx264",
            "-crf", "28",

            "-c:a", "aac",
            "-b:a", "96k",

            clip_path,
            "-y"
        ]

        subprocess.run(cmd, check=True, timeout=180)

        clips.append(clip_path)

        start += clip_length

    return clips

# -------------------------
# PROCESS VIDEO
# -------------------------

@app.post("/process-youtube")
def process_youtube(req: YoutubeRequest, email: str = Depends(verify_token)):

    try:

        video = download_youtube(req.url)

        audio = extract_audio(video)

        clips = generate_clips(video)

        public_clips = []

        for clip in clips:
            name = os.path.basename(clip)
            public_clips.append(f"/clips/{name}")

        return {
            "message": "Processing completed",
            "clips": public_clips
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------------
# LIST CLIPS
# -------------------------

@app.get("/clips")
def list_clips():

    files = os.listdir(CLIPS_DIR)

    clips = [
        f"/clips/{f}"
        for f in files
        if f.endswith(".mp4")
    ]

    return {"clips": clips}
