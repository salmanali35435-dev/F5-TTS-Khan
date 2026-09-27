import streamlit as st
import streamlit.components.v1 as components
import json
import os
import base64
import subprocess
import tempfile
import uuid
import threading
import shutil
import time
import re
import html
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
import requests
#
#
st.set_page_config( page_title="ZAIKO AI STUDIO", page_icon=" 🎙️", layout="wide", initial_sidebar_state="collapsed", )
# -------------------- INTERNAL CONFIG ----
REPO_OWNER = "salmanali35435-dev"
REPO_NAME = "F5-TTS-Khan"
DB_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/users_db.json"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/users_db.json"
GITHUB_PAT_TOKEN = str(st.secrets.get("GITHUB_PAT_TOKEN", "")).strip()
DATA_ROOT = Path("cloud_vault")
DATA_ROOT.mkdir(parents=True, exist_ok=True)
SESSIONS_FILE = DATA_ROOT / "_sessions.json"
SHARES_FILE = DATA_ROOT / "_shares.json"
_FILE_LOCKS = {}
_FILE_LOCKS_GUARD = threading.Lock()
WHATSAPP_NUMBER_INTL = "923097647772"
ADMIN_CONTACT_NAME = "Muhammad Zakriya"
BRAND = "ZAIKO AI STUDIO"
FOOTER_BY = "Built By M Zakriya"
HISTORY_RETENTION_DAYS = 7
SUPPORTED_VOICE_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
MAX_VOICE_SECONDS = 12.0
CLIENT_PAGES = ["Dashboard", "Voice Cloning", "Text To Speech", "History", "Settings", "Account"]
ADMIN_PAGES = ["Dashboard", "Active Users Registry", "Deploy New Client", "Settings"]
PAGE_ICONS = { "Dashboard": "⌂", "Voice Cloning": "◉", "Text To Speech": "♫", "History": "◷", "Settings": "⚙", "Account": "◎", "Active Users Registry": "♛", "Deploy New Client": "+", }
# -------------------- FILE HELPERS -------
def _lock_for(path: Path):
    key = str(path)
    with _FILE_LOCKS_GUARD:
        if key not in _FILE_LOCKS:
            _FILE_LOCKS[key] = threading.RLock()
        return _FILE_LOCKS[key]
def load_json(path: Path, default):
    lock = _lock_for(path)
    with lock:
        if not path.exists():
            return json.loads(json.dumps(default))
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw else None
            return data if data is not None else json.loads(json.dumps(default))
        except Exception:
            return json.loads(json.dumps(default))
def save_json(path: Path, data):
    lock = _lock_for(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
def user_dir(username):
    p = DATA_ROOT / username
    p.mkdir(parents=True, exist_ok=True)
    return p
def voice_dir(username):
    p = user_dir(username) / "voices"
    p.mkdir(parents=True, exist_ok=True)
    return p
def jobs_file(username):
    return user_dir(username) / "jobs.json"
def history_file(username):
    return user_dir(username) / "history.json"
def outputs_dir(username):
    p = user_dir(username) / "outputs"
    p.mkdir(parents=True, exist_ok=True)
    return p
def fallback_database():
    return { "AKKHAN": { "password": "AKKHAN90", "expiry_timestamp": "2030-12-31 23:59:59", "total_limit": 99999999, "total_credits_allocated": 99999999, "remaining_chars": 99999999, "is_revoked": False, "is_admin": True, "kaggle_username": "", "kaggle_token": "", } }
def fetch_live_database():
    try:
        r = requests.get(DB_URL, timeout=15)
        if r.status_code == 200:
            users = r.json().get("users", {})
            if users:
                for info in users.values():
                    info.setdefault("total_credits_allocated", int(info.get("total_limit", 0)))
                    return users
    except Exception:
        pass
    return fallback_database()
def push_database_updates(updated_db):
    if not GITHUB_PAT_TOKEN:
        return False
    headers = { "Authorization": f"Bearer {GITHUB_PAT_TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ZAIKO-AI-STUDIO", }
    try:
        r = requests.get(GITHUB_API_URL, headers=headers, timeout=15)
        if r.status_code != 200:
            return False
        payload = { "message": "Update ZAIKO AI STUDIO accounts", "content": base64.b64encode(json.dumps({"users": updated_db}, indent=2, ensure_ascii=False).encode()).decode("ascii"), "sha": r.json().get("sha"), }
        out = requests.put(GITHUB_API_URL, headers=headers, json=payload, timeout=15)
        return out.status_code in (200, 201)
    except Exception:
        return False
        # -------------------- GITHUB QUEUE --------------------

def _queue_path(username):
    return f"queue/{username}.json"
def _github_headers():
    return { "Authorization": f"Bearer {GITHUB_PAT_TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ZAIKO-AI-STUDIO", }
def github_read(path):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    try:
        r = requests.get(url, headers=_github_headers(), timeout=15)
        if r.status_code == 200:
            j = r.json()
            content = json.loads(base64.b64decode(j["content"]).decode("utf-8"))
            return content, j.get("sha")
            return None, None
    except Exception:
        return None, None
def github_write(path, data, sha=None, retries=2):
    if not GITHUB_PAT_TOKEN:
        return False
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    payload = { "message": f"update {path}", "content": base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf- 8")).decode("ascii"), }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=_github_headers(), json=payload, timeout=20)
        if r.status_code in (200, 201):
            return True
            if r.status_code == 409 and retries > 0:
                _, latest_sha = github_read(path)
                return github_write(path, data, sha=latest_sha, retries=retries - 1)
            return False
    except Exception:
        return False
def ensure_queue(username):
    content, sha = github_read(_queue_path(username))
    if content is None:
        content = {"jobs": [], "stop": False}
        github_write(_queue_path(username), content, sha=None)
        content, sha = github_read(_queue_path(username))
    return content, sha
def push_job_to_queue(username, job_id, text, voice_b64):
    content, sha = ensure_queue(username)
    if content is None:
        return False
    content["jobs"] = content.get("jobs", []) + [{"job_id": job_id, "text": text, "voice_b64": voice_b64}]
    content["stop"] = False
    return github_write(_queue_path(username), content, sha=sha)
def push_stop_flag(username):
    content, sha = ensure_queue(username)
    if content is None:
        return False
    content["stop"] = True
    return github_write(_queue_path(username), content, sha=sha)
    # -------------------- SESSION SECURITY ---
def load_sessions():
    return load_json(SESSIONS_FILE, {})
def save_sessions(data):
    save_json(SESSIONS_FILE, data)
def request_device_info():
    try:
        headers = st.context.headers
        ua = headers.get("User-Agent", "Unknown browser")
        ip = headers.get("X-Forwarded-For", headers.get("X-Real-IP", "Unavailable"))
        if "," in ip:
            ip = ip.split(",")[0].strip()
        return {"user_agent": ua, "ip": ip}
    except Exception:
        return {"user_agent": "Unknown browser", "ip": "Unavailable"}
def create_session(username):
    sessions = load_sessions()
    sid = uuid.uuid4().hex
    now = datetime.now().isoformat()
    device = request_device_info()
    sessions[sid] = { "username": username, "created": now, "last_seen": now, "user_agent": device.get("user_agent", "Unknown browser"), "ip": device.get("ip", "Unavailable"), }
    save_sessions(sessions)
    return sid
def touch_session(sid):
    sessions = load_sessions()
    if sid in sessions:
        sessions[sid]["last_seen"] = datetime.now().isoformat()
        save_sessions(sessions)
def resolve_session(sid):
    sessions = load_sessions()
    entry = sessions.get(sid)
    return entry.get("username") if entry else None
def remove_session(sid):
    if not sid:
        return
    sessions = load_sessions()
    if sid in sessions:
        del sessions[sid]
        save_sessions(sessions)
def sessions_for_user(username):
    return [{"sid": sid, **data} for sid, data in load_sessions().items() if data.get("username") == username]
def set_cookie(sid, max_age_days=30, reload=False):
    max_age = max_age_days * 86400
    reload_js = "setTimeout(function() {window.parent.location.reload();},150);" if reload else ""
    components.html( f'''<script> try {{ window.parent.document.cookie = "zaiko_session={sid}; path=/; max-age= {max_age}; samesite=Lax"; }} catch (e) {{}} document.cookie = "zaiko_session= {sid}; path=/; max-age={max_age}; samesite=Lax"; {reload_js} </script>''', height=0, )
def clear_cookie():
    components.html( '''<script> document.cookie="zaiko_session=; path=/; max-age=0; samesite=Lax"; setTimeout(function() {window.parent.location.reload();},150); </script>''', height=0, )
def cookie_session_id():
    try:
        return st.context.cookies.get("zaiko_session")
    except Exception:
        return None
    # -------------------- JOB / HISTORY / SHARE STORES --------------------
def create_job(username, job_type, payload):
    lock = _lock_for(jobs_file(username))
    with lock:
        jobs = load_json(jobs_file(username), {})
        jid = uuid.uuid4().hex
        now = datetime.now().isoformat()
        jobs[jid] = { "job_id": jid, "type": job_type, "status": "queued", "progress": 0.0, "message": "Preparing...", "created": now, "updated": now, "credits_charged": False, "history_recorded": False, "error": None, "result_file": None, **payload, }
        save_json(jobs_file(username), jobs)
        return jid
def update_job(username, jid, **fields):
    lock = _lock_for(jobs_file(username))
    with lock:
        jobs = load_json(jobs_file(username), {})
        if jid not in jobs:
            return jobs[jid].update(fields)
        jobs[jid]["updated"] = datetime.now().isoformat()
        save_json(jobs_file(username), jobs)
def get_job(username, jid):
    return load_json(jobs_file(username), {}).get(jid)
def all_jobs(username):
    return list(load_json(jobs_file(username), {}).values())
def active_job(username, job_type=None):
    jobs = all_jobs(username)
    active = [j for j in jobs if j.get("status") not in {"completed", "failed", "cancelled", "disconnected"}]
    if job_type:
        active = [j for j in active if j.get("type") == job_type]
    return max(active, key=lambda x: x.get("updated", "")) if active else None
def latest_job(username, job_type):
    jobs = [j for j in all_jobs(username) if j.get("type") == job_type]
    return max(jobs, key=lambda x: x.get("updated", "")) if jobs else None
def add_history(username, item):
    lock = _lock_for(history_file(username))
    with lock:
        items = load_json(history_file(username), [])
        items.append(item)
        save_json(history_file(username), items)
def prune_history(username):
    cutoff = datetime.now() - timedelta(days=HISTORY_RETENTION_DAYS)
    lock = _lock_for(history_file(username))
    with lock:
        items = load_json(history_file(username), [])
        kept = []
        for item in items:
            try:
                ts = datetime.fromisoformat(item["generated_at"] )
            except Exception:
                continue
            if ts >= cutoff:
                kept.append(item)
            else:
                Path(item.get("audio_path", "")).unlink(missing_ok=True)
        save_json(history_file(username), kept)
        return kept
def create_share(username, job_id):
    job = get_job(username, job_id)
    if not job or not job.get("result_file") or not Path(job["result_file"]).exists():
        return None
    shares = load_json(SHARES_FILE, {})
    token = uuid.uuid4().hex
    shares[token] = {"username": username, "job_id": job_id, "created": datetime.now().isoformat(), "expires": (datetime.now() + timedelta(days=7)).isoformat()}
    save_json(SHARES_FILE, shares)
    return token
def get_share(token):
    shares = load_json(SHARES_FILE, {})
    item = shares.get(token)
    if not item:
        return None
    try:
        if datetime.fromisoformat(item["expires"]) < datetime.now():
            return None
    except Exception:
        return None
    job = get_job(item["username"], item["job_id"])
    if not job or not job.get("result_file") or not Path(job["result_file"]).exists():
        return None
    return item, job
    # -------------------- VOICE HELPERS --------------------
def safe_filename(name):
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "_", name).strip()
    return cleaned or "audio"
def saved_voices(username):
    return sorted( [p for p in voice_dir(username).iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_VOICE_EXT], key=lambda p: p.name.lower(), )
def audio_duration_seconds(path: Path):
    if path.suffix.lower() != ".wav":
        return None
    try:
        import wave
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate() or 1)
    except Exception:
        return None
def uploaded_audio_duration(uploaded):
    suffix = Path(uploaded.name).suffix.lower()
    if suffix != ".wav":
        return None
    tmp = Path(tempfile.mkstemp(suffix=suffix)[1])
    try:
        tmp.write_bytes(uploaded.getbuffer())
        return audio_duration_seconds(tmp)
    finally:
        tmp.unlink(missing_ok=True)
        # -------------------- GENERATION BACKEND -
def verify_generation_credentials(username, token):
    if not username.strip():
        return False, False, "Enter a username."
    if not token.strip():
        return False, False, "Enter an API token."
    env = os.environ.copy()
    env["KAGGLE_USERNAME"] = username.strip()
    env["KAGGLE_API_TOKEN"] = token.strip()
    env["KAGGLE_KEY"] = token.strip()
    try:
        r = subprocess.run(["kaggle", "kernels", "list", "--mine"], env=env, capture_output=True, text=True, timeout=30, check=False)
        combined = ((r.stdout or "") + (r.stderr or "")).lower()
        if r.returncode == 0:
            return True, True, None
        if "401" in combined or "unauthorized" in combined or "invalid" in combined:
            return False, False, None
        return False, False, "Could not verify right now. Please try again."
    except FileNotFoundError:
        return False, False, "Verification tool is unavailable on this server."
    except Exception:
        return False, False, "Could not verify right now. Please try again."

QUEUE_TIMEOUT_SECONDS = 300  # 5 minutes
def kaggle_kernel_status(kernel_ref, env):
    try:
        r = subprocess.run(["kaggle", "kernels", "status", kernel_ref], env=env, capture_output=True, text=True, timeout=20, check=False)
        low = ((r.stdout or "") + (r.stderr or "")).lower()
        if "queued" in low:
            return "queued"
            if "running" in low:
                return "running"
            if "complete" in low:
                return "complete"
            if "error" in low or "cancel" in low:
                return "error"
            return "unknown"
    except Exception:
        return "unknown"
def _cleanup_stuck_kernel(kernel_ref, env):
    # Reset only the affected queued kernel.
    try:
        owner, slug = kernel_ref.split("/", 1)
        tmp = Path(tempfile.mkdtemp(prefix="zaiko_cleanup_"))
        (tmp / "server.ipynb").write_text(json.dumps({ "cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": ["print('cleared')\n"]}], "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5, }), encoding="utf-8")
        (tmp / "kernel-metadata.json").write_text(json.dumps({ "id": kernel_ref, "title": slug, "code_file": "server.ipynb", "language": "python", "kernel_type": "notebook", "is_private": True, "enable_gpu": False, "enable_internet": False, "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": [], }), encoding="utf-8")
        subprocess.run(["kaggle", "kernels", "push", "-p", str(tmp)], env=env, capture_output=True, text=True, check=False, timeout=30)
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass
def build_server_source(username):
    raw_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/queue/{username}.json"
    src = """import json, time, base64, subprocess, sys, urllib.request
from pathlib import Path
OUT = Path("/kaggle/working")
LOGS = []

def write_status(phase, message, extra=None):
    d = {"phase": phase, "message": message, "logs": LOGS[-12:]}
    if extra: d.update(extra)
    (OUT / "server_status.json").write_text(json.dumps(d), encoding="utf-8")

def log(msg):
    LOGS.append(msg); print(msg, flush=True); write_status("installing", msg)

def fetch_queue():
    try:
        req = urllib.request.Request("__RAW_URL__", headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

try:
    log("Starting engine, installing dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "f5-tts"])
    log("Loading F5-TTS model on GPU...")
    from f5_tts.api import F5TTS
    tts = F5TTS(model="F5TTS_v1_Base", device="cuda")
    write_status("ready", "Server ready")
    processed = set(); started = time.time()
    while True:
        q = fetch_queue()
        if q is None: time.sleep(5); continue
        if q.get("stop"):
            write_status("stopped", "Disconnected by user"); break
        for job in q.get("jobs", []):
            jid = job.get("job_id")
            if not jid or jid in processed: continue
            processed.add(jid)
            try:
                voice_path = OUT / f"voice_{jid}.wav"
                voice_path.write_bytes(base64.b64decode(job["voice_b64"]))
                audio_path = OUT / f"generated_{jid}.wav"
                (OUT / f"status_{jid}.json").write_text(json.dumps({"percent": 1, "message": "starting"}), encoding="utf-8")
                tts.infer(ref_file=str(voice_path), ref_text="", gen_text=job["text"], file_wave=str(audio_path), remove_silence=False)
                (OUT / f"status_{jid}.json").write_text(json.dumps({"percent": 100, "message": "done", "complete": True}), encoding="utf-8")
            except Exception as exc:
                (OUT / f"status_{jid}.json").write_text(json.dumps({"percent": 0, "message": str(exc), "error": True}), encoding="utf-8")
        if time.time() - started > 6 * 3600:
            write_status("stopped", "Session time limit reached"); break
        time.sleep(5)
except Exception as exc:
    write_status("error", repr(exc))
"""
    return src.replace("__RAW_URL__", raw_url)


def _poll_for_ready(username, job_id, kernel_ref, env, report, enforce_queue_timeout):
    queued_since = None
    last_logs = []
    for _ in range(240):
        if enforce_queue_timeout:
            k_status = kaggle_kernel_status(kernel_ref, env)
            if k_status == "queued":
                queued_since = queued_since or time.time()
                if time.time() - queued_since > QUEUE_TIMEOUT_SECONDS:
                    _cleanup_stuck_kernel(kernel_ref, env)
                    report(status="failed", error="This server instance stayed queued on Kaggle for over 5 minutes. Please try Connect again.", progress=0)
                    return False
            elif k_status == "running":
                queued_since = None
        probe_dir = Path(tempfile.mkdtemp(prefix="zaiko_probe_"))
        status_files = []
        try:
            subprocess.run(["kaggle", "kernels", "output", kernel_ref, "-p", str(probe_dir), "-o", "-q"], env=env, capture_output=True, text=True, check=False, timeout=30)
            status_files = list(probe_dir.rglob("server_status.json"))
            if status_files:
                payload = json.loads(status_files[0].read_text(encoding="utf-8")); phase = payload.get("phase"); logs = payload.get("logs", [])
                last_logs = logs
                if phase == "ready":
                    # Server backend is already up and initialized — bypass the
                    # installing/setup workflow entirely, even on the very first check.
                    report(status="connected", message="Connected", progress=100, logs=logs); return True
                if phase == "error": report(status="failed", error=payload.get("message", "Server failed to start."), logs=logs); return False
                if phase == "stopped": report(status="disconnected", message=payload.get("message", "Disconnected"), logs=logs); return False
                report(status="installing", message=payload.get("message", "Installing..."), progress=min(90, 15 + len(logs) * 6), logs=logs)
        except Exception:
            pass
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)
        if not status_files:
            # server_status.json is missing/unreadable — most commonly because Kaggle
            # has the notebook Queued and no code is executing yet. Fall back to the
            # live kernel status so the UI never freezes silently.
            fallback_status = kaggle_kernel_status(kernel_ref, env)
            if fallback_status == "queued":
                queue_message = "Kaggle Cloud Scheduler: Notebook is currently Queued on servers (Chup hai / waiting for free GPU cluster)..."
                last_logs = (last_logs + [queue_message])[-12:]
                report(status="installing", message=queue_message, progress=10, logs=last_logs)
            else:
                report(status="installing", message="Waiting for server status...", progress=max(10, min(90, 15 + len(last_logs) * 6)), logs=last_logs)
        time.sleep(4)
    report(status="failed", error="The server took too long to start. Please try again.")
    return False


def run_connect_job(username, job_id, gen_username, gen_token):
    def report(**fields): update_job(username, job_id, **fields)
    workspace = None
    try:
        ensure_queue(username)
        kernel_slug = re.sub(r"[^a-z0-9-]", "-", f"zaiko-srv-{username.lower()}").strip("-")[:80]
        kernel_ref = f"{gen_username}/{kernel_slug}"
        env = os.environ.copy(); env["KAGGLE_USERNAME"] = gen_username; env["KAGGLE_API_TOKEN"] = gen_token; env["KAGGLE_KEY"] = gen_token
        report(status="connecting", message="Checking for an existing server...", progress=5, kernel_ref=kernel_ref, logs=[])
        if kaggle_kernel_status(kernel_ref, env) == "running":
            # Do not force "installing" here — _poll_for_ready() will check the actual
            # server_status.json first and report "connected" immediately if the
            # backend is already ready, bypassing the setup workflow entirely.
            report(status="connecting", message="Checking existing server status...", progress=20)
            _poll_for_ready(username, job_id, kernel_ref, env, report, enforce_queue_timeout=False); return
        workspace = Path(tempfile.mkdtemp(prefix="zaiko_srv_")); notebook_path = workspace / "server.ipynb"; metadata_path = workspace / "kernel-metadata.json"
        source = build_server_source(username)
        notebook = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source.splitlines(True)}], "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
        notebook_path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
        metadata = {"id": kernel_ref, "title": kernel_slug, "code_file": "server.ipynb", "language": "python", "kernel_type": "notebook", "is_private": True, "enable_gpu": True, "enable_internet": True, "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": []}
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        report(status="connecting", message="Connecting to server...", progress=10)
        pushed = subprocess.run(["kaggle", "kernels", "push", "-p", str(workspace)], env=env, capture_output=True, text=True, check=False)
        if pushed.returncode != 0:
            report(status="failed", error="Could not start the server. Please check your generation credentials."); return
        report(status="installing", message="Server starting, installing dependencies...", progress=15)
        _poll_for_ready(username, job_id, kernel_ref, env, report, enforce_queue_timeout=True)
    except FileNotFoundError:
        update_job(username, job_id, status="failed", error="The generation service is not available right now.")
    except Exception:
        update_job(username, job_id, status="failed", error="Something went wrong while connecting. Please try again.")
    finally:
        if workspace: shutil.rmtree(workspace, ignore_errors=True)

def start_connection(username, gen_username, gen_token):
    jid = create_job(username, "connect", {})
    threading.Thread(target=run_connect_job, args=(username, jid, gen_username, gen_token), daemon=True).start()
    return jid
def disconnect_connection(username, jid):
    push_stop_flag(username)
    update_job(username, jid, status="disconnected", message="Disconnecting... this can take up to a minute while the server winds down.")
def run_tts_poll(username, job_id, kernel_ref, gen_username, gen_token, remote_job_id):
    env = os.environ.copy()
    env["KAGGLE_USERNAME"] = gen_username
    env["KAGGLE_API_TOKEN"] = gen_token
    env["KAGGLE_KEY"] = gen_token
    update_job(username, job_id, status="generating", progress=1, message="Queued on server...")
    for _ in range(400):
        probe_dir = Path(tempfile.mkdtemp(prefix="zaiko_gen_"))
        try:
            subprocess.run(["kaggle", "kernels", "output", kernel_ref, "-p", str(probe_dir), "-o", "-q"], env=env, capture_output=True, text=True, check=False, timeout=30)
            status_files = list(probe_dir.rglob(f"status_{remote_job_id}.json"))
            audio_files = list(probe_dir.rglob(f"generated_{remote_job_id}.wav"))
            if status_files:
                payload = json.loads(status_files[0].read_text(encoding="utf-8"))
                if payload.get("error"):
                    update_job(username, job_id, status="failed", error="Generation failed. Please try again.")
                    return
                pct = float(payload.get("percent", 1))
                update_job(username, job_id, progress=max(1, min(99, pct)), message=payload.get("message", "Generating..."))
            if audio_files and audio_files[0].stat().st_size > 1000:
                result = outputs_dir(username) / f"{job_id}.wav"
                result.write_bytes(audio_files[0].read_bytes())
                update_job(username, job_id, status="completed", progress=100, message="Speech generated successfully.", result_file=str(result))
                return
        except Exception:
            pass
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)
        time.sleep(3)
    update_job(username, job_id, status="failed", error="Generation took too long and was stopped. Please try again.")


def start_generation(username, text, title, voice_path, kernel_ref, gen_username, gen_token, char_count):
    jid = create_job(username, "tts", {"text": text, "title": title, "voice_path": str(voice_path), "voice_name": Path(voice_path).stem, "chars": char_count})
    remote_job_id = uuid.uuid4().hex[:12]
    voice_b64 = base64.b64encode(Path(voice_path).read_bytes()).decode("ascii")
    if not push_job_to_queue(username, remote_job_id, text, voice_b64):
        update_job(username, jid, status="failed", error="Could not reach the server. Please try again.")
        return jid
    threading.Thread(target=run_tts_poll, args=(username, jid, kernel_ref, gen_username, gen_token, remote_job_id), daemon=True).start()
    return jid


# -------------------- CREDITS --------------------
def charge_once(db, profile, username, jid, chars):
    job = get_job(username, jid)
    if not job or job.get("credits_charged"):
        return True
    remaining = int(profile.get("remaining_chars", 0))
    chars = int(chars or 0)
    if chars > remaining:
        return False
    profile["remaining_chars"] = remaining - chars
    if push_database_updates(db):
        update_job(username, jid, credits_charged=True)
        return True
    return False


# -------------------- UI --------------------
st.markdown("""
<style>
:root{--bg:#050a14;--panel:#0b1324;--panel2:#0e1a2d;--line:rgba(111,210,255,.16);--text:#eef7ff;--muted:#91a4bd;--cyan:#56dcff;--purple:#8b7cff}
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"]{background:radial-gradient(circle at 80% -10%,rgba(92,86,255,.12),transparent 34%),radial-gradient(circle at 10% 10%,rgba(0,210,255,.08),transparent 30%),var(--bg);color:var(--text)}
.block-container{max-width:1180px;padding-top:6.5rem;padding-bottom:2.5rem}
#MainMenu,footer,.stDeployButton,[data-testid="stDecoration"]{visibility:hidden!important;height:0!important}
header[data-testid="stHeader"]{background:transparent!important;height:0!important;min-height:0!important}
[data-testid="stSidebar"]{background:#070e1b;border-right:1px solid var(--line)}
.brand{font-weight:900;letter-spacing:.7px;font-size:1.25rem;background:linear-gradient(90deg,#56dcff,#8b7cff,#ff76cf);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.zhead{position:fixed;top:env(safe-area-inset-top,0px);left:0;right:0;z-index:9999;background:rgba(5,10,20,.91);backdrop-filter:blur(18px);border-bottom:1px solid var(--line);padding:14px 22px 14px 60px;min-height:58px;display:flex;align-items:center}
[data-testid="stSidebarCollapsedControl"]{position:fixed!important;top:calc(env(safe-area-inset-top,0px) + 12px)!important;left:16px!important;z-index:10000!important}
[data-testid="stSidebarCollapsedControl"] svg{display:none!important}
[data-testid="stSidebarCollapsedControl"]::after{content:"☰";font-size:1.5rem;color:#bfeeff}
.card,.hero{background:linear-gradient(145deg,rgba(14,26,46,.94),rgba(8,18,33,.91));border:1px solid rgba(126,211,255,.12);border-radius:20px;padding:24px;margin-bottom:18px;box-shadow:0 18px 45px rgba(0,0,0,.25)}
.card:hover{border-color:rgba(86,220,255,.22)}.hero h1{margin:0 0 6px}.muted,.small{color:var(--muted)}
.footer{text-align:center;margin-top:48px;padding:28px 10px;color:#8193aa;border-top:1px solid rgba(255,255,255,.07)}
.wa{display:inline-block;margin-top:10px;padding:10px 17px;border-radius:12px;border:1px solid rgba(86,220,255,.28);background:rgba(86,220,255,.08);color:#9eeaff!important;text-decoration:none;font-weight:800}
.login-wrap{max-width:520px;margin:7vh auto}.login-brand{text-align:center;font-size:2rem}.typewriter{min-height:86px;text-align:center;font-size:1.35rem;font-weight:900;line-height:1.45;background:linear-gradient(90deg,#56dcff,#8b7cff,#ff76cf);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:22px 0 26px}
.stButton>button{border-radius:12px;border:1px solid rgba(86,220,255,.18);min-height:44px}.stButton>button:disabled{background:#172238!important;color:#596982!important}
textarea[aria-label="Enter Your Text"]{height:260px!important;max-height:260px!important;overflow-y:auto!important}
[data-testid="stMetric"]{background:rgba(14,26,46,.68);border:1px solid rgba(126,211,255,.10);border-radius:16px;padding:14px}
@media(max-width:760px){.block-container{padding-top:6.5rem}.zhead{padding:10px 12px 10px 52px}.hero,.card{padding:18px;border-radius:16px}.login-wrap{margin:4vh auto}.typewriter{font-size:1.05rem}}
</style>
""", unsafe_allow_html=True)

# -------------------- SESSION STATE --------------------
for k, v in {
    "auth_session": False, "current_user": "", "session_id": "",
    "page": "Dashboard", "show_token": False, "settings_form_version": 0,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

share_token = st.query_params.get("share")
if share_token:
    shared = get_share(share_token)
    if shared:
        _, job = shared
        st.markdown(f'<div class="login-wrap"><div class="login-brand brand">{BRAND}</div><div class="card"><h2>{html.escape(job.get("title", "Shared Audio"))}</h2><p class="small">Voice: {html.escape(job.get("voice_name", ""))}</p>', unsafe_allow_html=True)
        audio = Path(job["result_file"])
        st.audio(audio.read_bytes(), format="audio/wav")
        st.download_button("Download Audio", audio.read_bytes(), file_name=f'{safe_filename(job.get("title", "audio"))}.wav', mime="audio/wav", use_container_width=True)
        st.markdown('</div></div>', unsafe_allow_html=True)
    else:
        st.error("This shared audio link has expired or is no longer available.")
    st.stop()

user_db = fetch_live_database()


def login_page():
    st.markdown(f'<div class="login-wrap"><div class="login-brand brand">{BRAND}</div><div class="typewriter">Give Your Words a Voice.</div><div class="card"><h2>Welcome back</h2>', unsafe_allow_html=True)
    with st.form("login_form"):
        username = st.text_input("Username", key="login_user").upper().strip()
        password = st.text_input("Password", type="password", key="login_pass")
        submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)
    if submitted:
        target = user_db.get(username)
        if not target or target.get("password") != password:
            st.error("Invalid username or password.")
        elif target.get("is_revoked"):
            st.error("This account no longer has access. Please contact support.")
        else:
            try:
                exp = datetime.strptime(target.get("expiry_timestamp", ""), "%Y-%m-%d %H:%M:%S")
            except Exception:
                exp = datetime.now() + timedelta(days=1)
            if exp < datetime.now() and not target.get("is_admin", False):
                st.error("Your plan has expired. Please contact support to renew.")
            else:
                sid = create_session(username)
                st.session_state.auth_session = True
                st.session_state.current_user = username
                st.session_state.session_id = sid
                st.session_state.page = "Dashboard"
                st.query_params["page"] = "Dashboard"
                st.query_params["sid"] = sid
                set_cookie(sid, reload=False)
                st.rerun()
    st.markdown('</div></div>', unsafe_allow_html=True)
    msg = quote(f"Hi {ADMIN_CONTACT_NAME}, I want to request access to {BRAND}.")
    st.markdown(f'<div class="card" style="text-align:center"><div style="font-weight:800">Need access?</div><div class="small">{ADMIN_CONTACT_NAME}</div><a class="wa" href="https://wa.me/{WHATSAPP_NUMBER_INTL}?text={msg}" target="_blank">💬 Contact on WhatsApp</a></div>', unsafe_allow_html=True)


if not st.session_state.auth_session:
    login_page()
    st.stop()

active_username = st.session_state.current_user
if active_username not in user_db or user_db[active_username].get("is_revoked", False):
    remove_session(st.session_state.session_id)
    st.session_state.auth_session = False
    st.session_state.current_user = ""
    clear_cookie()
    st.stop()

profile = user_db[active_username]
is_admin = bool(profile.get("is_admin", False))
valid_pages = ADMIN_PAGES if is_admin else CLIENT_PAGES
requested_page = st.query_params.get("page")
if requested_page in valid_pages:
    st.session_state.page = requested_page
if st.session_state.page not in valid_pages:
    st.session_state.page = valid_pages[0]
page = st.session_state.page


def goto(p):
    st.session_state.page = p
    st.query_params["page"] = p
    st.rerun()


def logout():
    remove_session(st.session_state.get("session_id", ""))
    st.session_state.clear()
    st.query_params.clear()
    clear_cookie()


def expiry_dt():
    try:
        return datetime.strptime(profile.get("expiry_timestamp", ""), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now()


def header():
    st.markdown(f'<div class="zhead"><div class="brand">{BRAND}</div><div style="margin-left:auto" class="small">{html.escape(active_username)}</div></div>', unsafe_allow_html=True)


def footer():
    msg = quote(f"Hi {ADMIN_CONTACT_NAME}, I need help with {BRAND}.")
    st.markdown(f'<div class="footer"><div class="brand">{BRAND}</div><div class="small">{FOOTER_BY}</div><a class="wa" href="https://wa.me/{WHATSAPP_NUMBER_INTL}?text={msg}" target="_blank">💬 Contact on WhatsApp</a></div>', unsafe_allow_html=True)


def nav():
    with st.sidebar:
        st.markdown(f'<div class="brand">{BRAND}</div>', unsafe_allow_html=True)
        for p in valid_pages:
            if st.button(f'{PAGE_ICONS.get(p, "•")}  {p}', key="nav_" + p, use_container_width=True):
                goto(p)
        st.divider()
        if st.button("Logout", use_container_width=True):
            logout(); st.rerun()


def page_dashboard():
    header(); st.markdown("## Dashboard")
    remaining = int(profile.get("remaining_chars", 0))
    total = int(profile.get("total_credits_allocated", profile.get("total_limit", 0)))
    sessions = sessions_for_user(active_username)
    jobs = all_jobs(active_username)
    completed = sum(1 for j in jobs if j.get("status") == "completed")
    a,b,c = st.columns(3)
    a.metric("Remaining Credits", f"{remaining:,}")
    b.metric("Total Credits", f"{total:,}")
    c.metric("Generated Voices", f"{completed:,}")
    st.markdown('<div class="hero"><h1>AI Voice Studio</h1><p class="muted">Create natural speech with your saved voice and F5-TTS.</p></div>', unsafe_allow_html=True)
    st.info(f"Account expires: {expiry_dt().strftime('%d %b %Y, %H:%M')}")
    st.caption(f"Connected devices: {len(sessions)}")
    footer()


def page_voice_cloning():
    header(); st.markdown("## Voice Cloning")
    st.markdown('<div class="card">Upload a short WAV reference voice. The generation backend uses it as the speaker reference.</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload Voice", type=[x.lstrip('.') for x in SUPPORTED_VOICE_EXT])
    if uploaded:
        duration = uploaded_audio_duration(uploaded)
        if duration is not None and duration > MAX_VOICE_SECONDS:
            st.error(f"Voice sample must be {MAX_VOICE_SECONDS:.0f} seconds or shorter.")
        else:
            name = safe_filename(Path(uploaded.name).stem)
            path = voice_dir(active_username) / f"{name}{Path(uploaded.name).suffix.lower()}"
            path.write_bytes(uploaded.getbuffer())
            st.success(f"Saved voice: {name}")
    st.markdown("### Saved Voices")
    voices = saved_voices(active_username)
    if not voices:
        st.info("No saved voices yet.")
    for v in voices:
        st.audio(v.read_bytes())
        if st.button("Delete", key="del_voice_" + v.name):
            v.unlink(missing_ok=True); st.rerun()
    footer()


def page_tts():
    header(); st.markdown("## Text To Speech")
    voices = saved_voices(active_username)
    if not voices:
        st.warning("Upload a voice sample first from Voice Cloning."); footer(); return
    active = active_job(active_username, "tts")
    options = [v.stem for v in voices]
    voice_name = st.selectbox("Reference Voice", options)
    selected = next(v for v in voices if v.stem == voice_name)
    text = st.text_area("Enter Your Text", height=260, placeholder="Type your text here...", disabled=bool(active))
    count = len(text)
    rem = int(profile.get("remaining_chars", 0))
    st.caption(f"Characters: {count:,} • Remaining credits: {rem:,}")
    title = st.text_input("Audio Title", value="Generated Voice", disabled=bool(active))
    connected = bool(profile.get("kaggle_username") and profile.get("kaggle_token"))
    if not connected:
        st.warning("Connect your Kaggle credentials in Settings before generating speech.")
    if count > rem:
        st.error("Not enough credits for this script.")
    if st.button("Generate Speech", type="primary", use_container_width=True, disabled=bool(active) or count == 0 or not connected or count > rem):
        kernel_ref = f'{profile.get("kaggle_username")}/zaiko-srv-{active_username.lower()}'
        jid = start_generation(active_username, text, title, selected, kernel_ref, profile["kaggle_username"], profile["kaggle_token"], count)
        if charge_once(user_db, profile, active_username, jid, count):
            st.success("Generation started.")
        else:
            st.error("Credits could not be charged; generation may need to be retried.")
        st.rerun()
    if active:
        st.progress(int(active.get("progress", 0)))
        st.write(active.get("message", "Generating..."))
    jobs = [j for j in all_jobs(active_username) if j.get("type") == "tts" and j.get("status") == "completed" and j.get("result_file")]
    if jobs:
        latest = max(jobs, key=lambda x: x.get("updated", x.get("created", "")))
        audio = Path(latest["result_file"])
        if audio.exists(): st.audio(audio.read_bytes(), format="audio/wav")
    footer()


def page_history():
    header(); st.markdown("## History")
    items = prune_history(active_username)
    if not items:
        st.info("No history yet."); footer(); return
    for item in reversed(items):
        st.markdown(f'<div class="card"><strong>{html.escape(item.get("title", "Audio"))}</strong><div class="small">{html.escape(item.get("voice_name", ""))} • {html.escape(item.get("generated_at", ""))}</div></div>', unsafe_allow_html=True)
        audio = Path(item.get("audio_path", ""))
        if audio.exists():
            st.audio(audio.read_bytes(), format="audio/wav")
            st.download_button("Download", audio.read_bytes(), file_name=f'{safe_filename(item.get("title", "audio"))}.wav', mime="audio/wav", key="dl_" + item.get("job_id", uuid.uuid4().hex))
    footer()


def page_settings():
    header(); st.markdown("## Settings")
    with st.form("connection_form"):
        u = st.text_input("Kaggle Username", value=profile.get("kaggle_username", ""))
        t = st.text_input("API Token", value=profile.get("kaggle_token", ""), type="password")
        save = st.form_submit_button("Save Credentials", type="primary", use_container_width=True)
    if save:
        if not u.strip() or not t.strip(): st.error("Username and API token are required.")
        else:
            profile.update({"kaggle_username": u.strip(), "kaggle_token": t.strip()})
            if push_database_updates(user_db): st.success("Credentials saved successfully.")
            else: st.error("Unable to save credentials right now.")
    footer()


def page_account():
    header(); st.markdown("## Account")
    a,b,c = st.columns(3)
    a.metric("Total Credits", f'{int(profile.get("total_credits_allocated", profile.get("total_limit", 0))):,}')
    b.metric("Remaining Credits", f'{int(profile.get("remaining_chars", 0)):,}')
    c.metric("Status", "Active")
    with st.form("change_password"):
        old = st.text_input("Current Password", type="password")
        new = st.text_input("New Password", type="password")
        change = st.form_submit_button("Change Password", use_container_width=True)
    if change:
        if profile.get("password") != old: st.error("Current password is incorrect.")
        elif not new: st.error("Please enter a new password.")
        else:
            profile["password"] = new
            if push_database_updates(user_db): st.success("Password changed successfully.")
            else: st.error("Unable to change password right now.")
    footer()


def admin_dashboard():
    header(); st.markdown("## Admin Dashboard")
    regular = [x for x in user_db.values() if not x.get("is_admin", False)]
    active = sum(1 for x in regular if not x.get("is_revoked", False))
    a,b = st.columns(2); a.metric("Total Clients", len(regular)); b.metric("Active Clients", active); footer()


def admin_registry():
    header(); st.markdown("## Active Users Registry")
    for n,x in [(n,x) for n,x in user_db.items() if not x.get("is_admin", False)]:
        with st.expander(f'{n} — {"Revoked" if x.get("is_revoked") else "Active"}'):
            st.write(f'Remaining credits: {int(x.get("remaining_chars",0)):,}')
            add = st.number_input("Add Credits", min_value=0, value=0, key="add_"+n)
            days = st.number_input("Extend Plan Days", min_value=0, value=0, key="days_"+n)
            if st.button("Revoke / Grant", key="toggle_"+n):
                x["is_revoked"] = not x.get("is_revoked", False); push_database_updates(user_db); st.rerun()
            if st.button("Save Changes", key="save_"+n):
                if add: x["remaining_chars"] = int(x.get("remaining_chars",0)) + int(add); x["total_credits_allocated"] = int(x.get("total_credits_allocated",x.get("total_limit",0))) + int(add)
                if days:
                    e = datetime.strptime(x.get("expiry_timestamp"), "%Y-%m-%d %H:%M:%S")
                    x["expiry_timestamp"] = (max(e, datetime.now()) + timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
                if push_database_updates(user_db): st.success("Changes saved."); st.rerun()
    footer()


def admin_deploy():
    header(); st.markdown("## Deploy New Client")
    with st.form("deploy_form"):
        u = st.text_input("New Client Username").upper().strip()
        pw = st.text_input("Set Login Password", type="password")
        days = st.number_input("Plan Duration (Days)", min_value=1, value=30)
        chars = st.number_input("Character Allocation", min_value=1000, value=1000000)
        go = st.form_submit_button("Deploy User", type="primary", use_container_width=True)
    if go:
        if not u or not pw: st.error("Username and password are required.")
        elif u in user_db: st.error("That username already exists.")
        else:
            amount = int(chars)
            user_db[u] = {"password": pw, "expiry_timestamp": (datetime.now()+timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S"), "total_limit": amount, "total_credits_allocated": amount, "remaining_chars": amount, "is_revoked": False, "is_admin": False, "kaggle_username": "", "kaggle_token": ""}
            if push_database_updates(user_db): st.success(f"User {u} created successfully."); st.rerun()
            else: st.error("We couldn't create the account right now.")
    footer()


def admin_settings():
    header(); st.markdown("## Settings"); st.info("Core storage configuration is managed securely outside this interface."); footer()


nav()
if is_admin:
    routes = {"Dashboard": admin_dashboard, "Active Users Registry": admin_registry, "Deploy New Client": admin_deploy, "Settings": admin_settings}
else:
    routes = {"Dashboard": page_dashboard, "Voice Cloning": page_voice_cloning, "Text To Speech": page_tts, "History": page_history, "Settings": page_settings, "Account": page_account}
routes.get(page, routes[valid_pages[0]])()
