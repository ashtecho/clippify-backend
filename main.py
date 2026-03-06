import os
import time
import subprocess
from typing import List

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import jwt
import yt_dlp


# -------------------------
# CONFIG
# -------------------------

SECRET_KEY = "clippify_secret_key"
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

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve clips publicly
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

    payload = {
        "email": email,
        "exp": int(time.time()) + 86400
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    return token


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):

    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["email"]

    except:
        raise HTTPException(status_code=401, detail="Invalid token")


# -------------------------
# BASIC ROUTES
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
# DASHBOARD
# -------------------------

@app.get("/dashboard")
def dashboard(email: str = Depends(verify_token)):

    return {"message": f"Welcome {email}"}


# -------------------------
# DOWNLOAD YOUTUBE VIDEO
# -------------------------

def download_youtube(url: str):

    filename = f"{DOWNLOAD_DIR}/video_{int(time.time())}.mp4"

    ydl_opts = {
        "format": "mp4",
        "outtmpl": filename
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return filename


# -------------------------
# EXTRACT AUDIO
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

    subprocess.run(cmd)

    return audio_path


# -------------------------
# GENERATE VERTICAL SHORTS
# -------------------------

def generate_clips(video_path: str):

    clips = []

    clip_length = 35
    max_clips = 5

    for i in range(max_clips):

        start = i * clip_length

        clip_path = f"{CLIPS_DIR}/clip_{i}.mp4"

        cmd = [
            "ffmpeg",
            "-ss", str(start),
            "-t", str(clip_length),
            "-i", video_path,

            # convert horizontal video to vertical
            "-vf", "crop=in_h*9/16:in_h:(in_w-in_h*9/16)/2:0,scale=1080:1920",

            "-preset", "ultrafast",
            "-c:v", "libx264",
            "-c:a", "aac",

            clip_path,
            "-y"
        ]

        subprocess.run(cmd)

        clips.append(f"/clips/clip_{i}.mp4")

    return clips


# -------------------------
# PROCESS YOUTUBE
# -------------------------

@app.post("/process-youtube")
def process_youtube(req: YoutubeRequest, email: str = Depends(verify_token)):

    video = download_youtube(req.url)

    extract_audio(video)

    clips = generate_clips(video)

    return {
        "message": "Processing completed",
        "clips": clips
    }


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
