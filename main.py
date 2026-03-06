from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import json
import bcrypt
import jwt
import datetime
import os
import subprocess
import shutil
from faster_whisper import WhisperModel

app = FastAPI(title="Clippify Auth API")

SECRET_KEY = "clippify_secret_key"
security = HTTPBearer()

os.makedirs("uploads", exist_ok=True)
os.makedirs("audio", exist_ok=True)
os.makedirs("transcripts", exist_ok=True)

# load whisper model
model = WhisperModel("small", compute_type="int8")

class User(BaseModel):
    email: EmailStr
    password: str


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload
    except:
        raise HTTPException(status_code=401, detail="Invalid token")
@app.get("/")
def home():
    return {"message": "Welcome to Clippify backend", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/signup")
def signup(user: User):

    with open("users.json", "r") as f:
        users = json.load(f)

    for u in users:
        if u["email"] == user.email:
            raise HTTPException(status_code=400, detail="Email exists")

    hashed = bcrypt.hashpw(user.password.encode(), bcrypt.gensalt())

    users.append({
        "email": user.email,
        "password": hashed.decode()
    })

    with open("users.json", "w") as f:
        json.dump(users, f)

    return {"message": "User created successfully"}

@app.post("/login")
def login(user: User):

    with open("users.json", "r") as f:
        users = json.load(f)

    for u in users:

        if u["email"] == user.email:

            if bcrypt.checkpw(user.password.encode(), u["password"].encode()):

                payload = {
                    "email": user.email,
                    "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)
                }

                token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

                return {
                    "message": "Login successful",
                    "access_token": token
                }

            raise HTTPException(status_code=401, detail="Invalid password")

    raise HTTPException(status_code=404, detail="User not found")

@app.get("/dashboard")
def dashboard(user=Depends(verify_token)):
    return {"message": "Welcome", "user": user["email"]}


# PROCESS VIDEO PIPELINE
def process_video(video_path):

    filename = os.path.basename(video_path)
    audio_path = f"audio/{filename}.wav"
    transcript_path = f"transcripts/{filename}.txt"

    # extract audio
    subprocess.run([
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        audio_path
    ])

    # transcribe
    segments, info = model.transcribe(audio_path)

    with open(transcript_path, "w") as f:
        for segment in segments:
            line = f"{segment.start:.2f} --> {segment.end:.2f} | {segment.text}\n"
            f.write(line)


@app.post("/upload-video")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user=Depends(verify_token)
):

    video_path = f"uploads/{file.filename}"

    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    background_tasks.add_task(process_video, video_path)

    return {
        "message": "Upload successful. AI processing started.",
        "video_saved": video_path,
        "status": "processing"
    }
