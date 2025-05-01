import os
import json
import uuid
import time
from typing import List
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from linkedin_api import Linkedin
import requests

SESSIONS_DIR = "/data/sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

app = FastAPI(title="LinkedIn Automation API v3", version="3.0.0")

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

def save_session(session_id: str, cookies: dict):
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    with open(path, "w") as f:
        json.dump(cookies, f)

def load_session(session_id: str):
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Session not found")
    return json.load(open(path))

@app.post("/login")
async def login(req: LoginRequest):
    try:
        api = Linkedin(req.username, req.password, refresh_cookies=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Login failed: {e}")
    # extract required cookies
    cookies = api.client.session.cookies.get_dict()
    if "li_at" not in cookies or "JSESSIONID" not in cookies:
        raise HTTPException(status_code=500, detail="Required cookies missing after login")
    session_id = str(uuid.uuid4())
    save_session(session_id, {"li_at": cookies["li_at"], "JSESSIONID": cookies["JSESSIONID"]})
    return {"session_id": session_id}

@app.post("/login-cookie")
async def login_cookie(req: CookieLoginRequest):
    # Build a requests session to fetch JSESSIONID
    sess = requests.Session()
    sess.cookies.set("li_at", req.li_at, domain=".linkedin.com")
    # Hit homepage to get JSESSIONID
    resp = sess.get("https://www.linkedin.com")
    jsid = sess.cookies.get("JSESSIONID")
    if not jsid:
        raise HTTPException(status_code=400, detail="Could not retrieve JSESSIONID from cookie")
    # Test with linkedin-api client
    cookies = {"li_at": req.li_at, "JSESSIONID": jsid}
    try:
        client = Linkedin(None, None, cookies=cookies)
        client.get_profile("me")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cookie login failed: {e}")
    session_id = str(uuid.uuid4())
    save_session(session_id, cookies)
    return {"session_id": session_id}

def get_client(session_id: str) -> Linkedin:
    cookies = load_session(session_id)
    return Linkedin(None, None, cookies=cookies)

@app.get("/sessions")
async def list_sessions():
    return {"sessions": [f[:-5] for f in os.listdir(SESSIONS_DIR) if f.endswith(".json")]}

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return {"deleted": session_id}
    raise HTTPException(status_code=404, detail="Session not found")

@app.post("/send")
async def send_message(req: SendRequest):
    client = get_client(req.session_id)
    results = {}
    for username in req.recipients:
        try:
            profile = client.get_profile(username)
            conv = client.get_conversation(profile.get("profile_id"))
            client.send_message(conv.get("id"), req.message)
            results[username] = "sent"
        except Exception as e:
            results[username] = f"error: {e}"
        if req.interval > 0:
            time.sleep(req.interval)
    return {"results": results}

@app.get("/profile/{username}")
async def get_profile(username: str, session_id: str = Query(...)):
    client = get_client(session_id)
    return client.get_profile(username)

@app.get("/search")
async def search_profiles(keywords: str, session_id: str = Query(...), limit: int = Query(10)):
    client = get_client(session_id)
    results = client.search_people(keywords=keywords)
    return {"results": results[:limit]}

@app.get("/connections")
async def get_connections(session_id: str = Query(...), limit: int = Query(None)):
    client = get_client(session_id)
    conns = client.get_profile_connections("me")
    return {"connections": conns[:limit] if limit else conns}