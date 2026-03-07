import os
import time
import subprocess

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import jwt
import yt_dlp
from faster_whisper import WhisperModel


# -------------------------
# CONFIG
# -------------------------

SECRET_KEY = "clippify_secret_key"
ALGORITHM = "HS256"

DOWNLOAD_DIR = "downloads"
AUDIO_DIR = "audio"
CLIPS_DIR = "clips"
SUB_DIR = "subs"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(SUB_DIR, exist_ok=True)

# lightweight whisper model
model = WhisperModel("tiny", compute_type="int8")


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

    payload = {
        "email": email,
        "exp": int(time.time()) + 86400
    }

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


@app.post("/signup")
def signup(user: User):

    if user.email in users_db:
        raise HTTPException(status_code=400, detail="User exists")

    users_db[user.email] = user.password

    return {"message": "Signup successful"}


@app.post("/login")
def login(user: User):

    if users_db.get(user.email) != user.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user.email)

    return {"access_token": token}


# -------------------------
# DOWNLOAD YOUTUBE
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

def extract_audio(video):

    audio = f"{AUDIO_DIR}/{os.path.basename(video)}.wav"

    cmd = [
        "ffmpeg",
        "-i", video,
        "-ar", "16000",
        "-ac", "1",
        "-vn",
        audio,
        "-y"
    ]

    subprocess.run(cmd)

    return audio


# -------------------------
# CAPTION GENERATION
# -------------------------

def generate_subtitles(audio):

    segments, info = model.transcribe(audio)

    srt = f"{SUB_DIR}/{os.path.basename(audio)}.srt"

    with open(srt, "w") as f:

        for i, seg in enumerate(segments, start=1):

            start = seg.start
            end = seg.end
            text = seg.text

            f.write(f"{i}\n")
            f.write(f"{format_time(start)} --> {format_time(end)}\n")
            f.write(f"{text}\n\n")

    return srt


def format_time(seconds):

    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)

    return f"{hrs:02}:{mins:02}:{secs:02},{ms:03}"


# -------------------------
# GENERATE SHORTS
# -------------------------

def generate_clips(video, subs):

    clips = []

    clip_length = 35
    max_clips = 5

    for i in range(max_clips):

        start = i * clip_length

        clip = f"{CLIPS_DIR}/clip_{i}.mp4"

        cmd = [
            "ffmpeg",
            "-ss", str(start),
            "-t", str(clip_length),
            "-i", video,
            "-vf",
            f"crop=in_h*9/16:in_h:(in_w-in_h*9/16)/2:0,scale=1080:1920,subtitles={subs}",
            "-preset", "ultrafast",
            "-c:v", "libx264",
            "-c:a", "aac",
            clip,
            "-y"
        ]

        subprocess.run(cmd)

        clips.append(f"/clips/clip_{i}.mp4")

    return clips


# -------------------------
# MAIN PROCESS
# -------------------------

@app.post("/process-youtube")
def process(req: YoutubeRequest, email: str = Depends(verify_token)):

    video = download_youtube(req.url)

    audio = extract_audio(video)

    subs = generate_subtitles(audio)

    clips = generate_clips(video, subs)

    return {
        "message": "Processing completed",
        "clips": clips
    }
