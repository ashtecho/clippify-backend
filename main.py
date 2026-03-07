import os
import time
import subprocess
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import jwt
import yt_dlp

SECRET_KEY = "clippify_secret"
ALGORITHM = "HS256"

DOWNLOAD_DIR = "downloads"
CLIPS_DIR = "clips"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)

app = FastAPI()

# --------------------
# CORS
# --------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/clips", StaticFiles(directory="clips"), name="clips")

security = HTTPBearer()

users = {}

class User(BaseModel):
    email: str
    password: str

class YoutubeRequest(BaseModel):
    url: str

# --------------------
# AUTH
# --------------------

def create_token(email):

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

# --------------------
# ROUTES
# --------------------

@app.get("/")
def root():
    return {"status": "Clippify running"}

@app.post("/signup")
def signup(user: User):

    if user.email in users:
        raise HTTPException(status_code=400, detail="User exists")

    users[user.email] = user.password

    return {"message": "Signup successful"}

@app.post("/login")
def login(user: User):

    if users.get(user.email) != user.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user.email)

    return {"access_token": token}

# --------------------
# VIDEO DOWNLOAD
# --------------------

def download_video(url):

    filename = f"{DOWNLOAD_DIR}/video_{int(time.time()*1000)}.mp4"

    ydl_opts = {
        "format": "best[ext=mp4]",
        "outtmpl": filename,
        "noplaylist": True,
        "quiet": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    duration = info["duration"]

    return filename, duration

# --------------------
# CLIP GENERATION
# --------------------

def generate_clips(video_path, duration):

    clip_length = 35

    clips = []

    # calculate number of clips
    clip_count = max(2, duration // clip_length)

    start = 0

    for i in range(int(clip_count)):

        clip_file = f"{CLIPS_DIR}/clip_{int(time.time())}_{i}.mp4"

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
            clip_file,
            "-y"
        ]

        subprocess.run(cmd)

        clips.append(clip_file)

        start += clip_length

        if start > duration:
            break

    return clips

# --------------------
# PROCESS VIDEO
# --------------------

@app.post("/process-youtube")
def process_youtube(req: YoutubeRequest, email: str = Depends(verify_token)):

    try:

        video, duration = download_video(req.url)

        clips = generate_clips(video, duration)

        public_clips = []

        for c in clips:

            name = os.path.basename(c)

            public_clips.append(f"/clips/{name}")

        return {
            "message": "Processing completed",
            "clips": public_clips
        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))

# --------------------
# LIST CLIPS
# --------------------

@app.get("/clips")
def list_clips():

    files = os.listdir(CLIPS_DIR)

    return {
        "clips": [f"/clips/{f}" for f in files if f.endswith(".mp4")]
    }
