from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import bcrypt
import jwt
import json
import os
import requests
from datetime import datetime, timedelta
import ffmpeg
from faster_whisper import WhisperModel

app = FastAPI(title="Clippify API")

# =========================
# CONFIG
# =========================

SECRET_KEY = "clippify-secret-key"
ALGORITHM = "HS256"

security = HTTPBearer()

# =========================
# LOAD WHISPER MODEL
# =========================

whisper_model = WhisperModel("base", compute_type="int8")

# =========================
# CREATE FOLDERS
# =========================

os.makedirs("videos", exist_ok=True)
os.makedirs("audio", exist_ok=True)
os.makedirs("clips", exist_ok=True)

# =========================
# USER MODEL
# =========================

class User(BaseModel):
    email: EmailStr
    password: str

class VideoURL(BaseModel):
    video_url: str

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
# DOWNLOAD VIDEO
# =========================

def download_video(url):

    filename = url.split("/")[-1]
    video_path = f"videos/{filename}"

    r = requests.get(url, stream=True)

    if r.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to download video")

    with open(video_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024*1024):
            if chunk:
                f.write(chunk)

    return video_path

# =========================
# EXTRACT AUDIO
# =========================

def extract_audio(video_path):

    filename = os.path.basename(video_path)
    audio_path = f"audio/{filename}.wav"

    (
        ffmpeg
        .input(video_path)
        .output(audio_path, ac=1, ar="16000")
        .run(overwrite_output=True)
    )

    return audio_path

# =========================
# WHISPER TRANSCRIPTION
# =========================

def transcribe_audio(audio_path):

    segments, info = whisper_model.transcribe(audio_path)

    transcript = []

    for segment in segments:
        transcript.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text
        })

    return transcript

# =========================
# ROUTES
# =========================

@app.get("/")
def home():
    return {"message": "Clippify backend running", "docs": "/docs"}

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
# PROCESS VIDEO FROM URL
# =========================

@app.post("/process-video-url")
def process_video(video: VideoURL, payload = Depends(verify_token)):

    video_path = download_video(video.video_url)

    audio_file = extract_audio(video_path)

    transcript = transcribe_audio(audio_file)

    return {
        "message": "Video processed successfully",
        "video_saved": video_path,
        "audio_file": audio_file,
        "segments_detected": len(transcript),
        "transcript_preview": transcript[:10]
    }
