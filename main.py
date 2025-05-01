import os
import json
import uuid
import time
from typing import List
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from linkedin_api import Linkedin

SESSIONS_DIR = "/data/sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

app = FastAPI(title="LinkedIn Automation API v2", version="2.0.0")

class LoginRequest(BaseModel):
    username: str
    password: str

class CookieLoginRequest(BaseModel):
    li_at: str

class SendRequest(BaseModel):
    session_id: str
    recipients: List[str]
    message: str
    interval: float = 0.0

@app.post("/login")
async def login(req: LoginRequest):
    try:
        api = Linkedin(req.username, req.password, refresh_cookies=True)
    except Exception as e:
        detail = str(e)
        raise HTTPException(status_code=400, detail=f"Login failed: {detail}")
    session_id = str(uuid.uuid4())
    cookies = api.client.session.cookies.get_dict()
    with open(os.path.join(SESSIONS_DIR, f"{session_id}.json"), "w") as f:
        json.dump({"li_at": cookies.get("li_at")}, f)
    return {"session_id": session_id}

@app.post("/login-cookie")
async def login_cookie(req: CookieLoginRequest):
    api = Linkedin(None, None, cookies={"li_at": req.li_at})
    # test call
    try:
        api.get_profile("me")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cookie login failed: {e}")
    session_id = str(uuid.uuid4())
    with open(os.path.join(SESSIONS_DIR, f"{session_id}.json"), "w") as f:
        json.dump({"li_at": req.li_at}, f)
    return {"session_id": session_id}

def load_api(session_id: str) -> Linkedin:
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Session not found")
    data = json.load(open(path))
    return Linkedin(None, None, cookies={"li_at": data["li_at"]})

@app.get("/sessions")
async def list_sessions():
    ids = [f[:-5] for f in os.listdir(SESSIONS_DIR) if f.endswith(".json")]
    return {"sessions": ids}

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return {"deleted": session_id}
    raise HTTPException(status_code=404, detail="Session not found")

@app.post("/send")
async def send_message(req: SendRequest):
    api = load_api(req.session_id)
    results = {}
    for username in req.recipients:
        try:
            profile = api.get_profile(username)
            conv = api.get_conversation(profile.get("profile_id"))
            api.send_message(conv.get("id"), req.message)
            results[username] = "sent"
        except Exception as e:
            results[username] = f"error: {e}"
        if req.interval > 0:
            time.sleep(req.interval)
    return {"results": results}

@app.get("/profile/{username}")
async def get_profile(username: str, session_id: str = Query(...)):
    api = load_api(session_id)
    return api.get_profile(username)

@app.get("/search")
async def search_profiles(keywords: str, session_id: str = Query(...), limit: int = Query(10)):
    api = load_api(session_id)
    results = api.search_people(keywords=keywords)
    return {"results": results[:limit]}

@app.get("/connections")
async def get_connections(session_id: str = Query(...), limit: int = Query(None)):
    api = load_api(session_id)
    conns = api.get_profile_connections("me")
    return {"connections": conns[:limit] if limit else conns}