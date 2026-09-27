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

# ============================================================
# ZAIKO AI STUDIO
# ============================================================

st.set_page_config(
    page_title="ZAIKO AI STUDIO",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# -------------------- INTERNAL CONFIG --------------------
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
PAGE_ICONS = {
    "Dashboard": "⌂", "Voice Cloning": "◉", "Text To Speech": "♫",
    "History": "◷", "Settings": "⚙", "Account": "◎",
    "Active Users Registry": "♛", "Deploy New Client": "+",
}

# -------------------- FILE HELPERS --------------------

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
    return {
        "AKKHAN": {
            "password": "AKKHAN90",
            "expiry_timestamp": "2030-12-31 23:59:59",
            "total_limit": 99999999,
            "total_credits_allocated": 99999999,
            "remaining_chars": 99999999,
            "is_revoked": False,
            "is_admin": True,
            "kaggle_username": "",
            "kaggle_token": "",
        }
    }


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
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ZAIKO-AI-STUDIO",
    }
    try:
        r = requests.get(GITHUB_API_URL, headers=headers, timeout=15)
        if r.status_code != 200:
            return False
        payload = {
            "message": "Update ZAIKO AI STUDIO accounts",
            "content": base64.b64encode(json.dumps({"users": updated_db}, indent=2, ensure_ascii=False).encode()).decode("ascii"),
            "sha": r.json().get("sha"),
        }
        out = requests.put(GITHUB_API_URL, headers=headers, json=payload, timeout=15)
        return out.status_code in (200, 201)
    except Exception:
        return False

# -------------------- GITHUB QUEUE (used to talk to a running Kaggle server) --------------------
# NOTE: the Kaggle kernel only ever performs unauthenticated GET requests against the
# public raw file below. The GITHUB_PAT_TOKEN itself is never embedded in kernel source,
# so a client can never see or use it even though the kernel runs on their own Kaggle account.

def _queue_path(username):
    return f"queue/{username}.json"


def _github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_PAT_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ZAIKO-AI-STUDIO",
    }


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
    payload = {
        "message": f"update {path}",
        "content": base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii"),
    }
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

# -------------------- SESSION SECURITY --------------------

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
    sessions[sid] = {
        "username": username,
        "created": now,
        "last_seen": now,
        "user_agent": device.get("user_agent", "Unknown browser"),
        "ip": device.get("ip", "Unavailable"),
    }
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
    reload_js = "setTimeout(function(){window.parent.location.reload();},150);" if reload else ""
    components.html(
        f'''<script>
        try {{
            window.parent.document.cookie = "zaiko_session={sid}; path=/; max-age={max_age}; samesite=Lax";
        }} catch (e) {{}}
        document.cookie = "zaiko_session={sid}; path=/; max-age={max_age}; samesite=Lax";
        {reload_js}
        </script>''',
        height=0,
    )


def clear_cookie():
    components.html(
        '''<script>
        document.cookie="zaiko_session=; path=/; max-age=0; samesite=Lax";
        setTimeout(function(){window.parent.location.reload();},150);
        </script>''',
        height=0,
    )


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
        jobs[jid] = {
            "job_id": jid, "type": job_type, "status": "queued", "progress": 0.0,
            "message": "Preparing...", "created": now, "updated": now,
            "credits_charged": False, "history_recorded": False, "error": None,
            "result_file": None, **payload,
        }
        save_json(jobs_file(username), jobs)
        return jid


def update_job(username, jid, **fields):
    lock = _lock_for(jobs_file(username))
    with lock:
        jobs = load_json(jobs_file(username), {})
        if jid not in jobs:
            return
        jobs[jid].update(fields)
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
                ts = datetime.fromisoformat(item["generated_at"])
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
    return sorted(
        [p for p in voice_dir(username).iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_VOICE_EXT],
        key=lambda p: p.name.lower(),
    )


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

# -------------------- GENERATION BACKEND --------------------

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


QUEUE_TIMEOUT_SECONDS = 300  # 5 minutes stuck in Kaggle's "queued" state


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
    # Kaggle's public API has no documented "cancel/delete a queued kernel" endpoint.
    # The closest safe equivalent is pushing a trivial, instantly-finishing version
    # to this EXACT kernel id. Kaggle only ever runs one active version per kernel,
    # so this supersedes the stuck queued run without touching any other notebook
    # on the account ("Your Work" and every other kernel are left untouched).
    try:
        owner, slug = kernel_ref.split("/", 1)
        tmp = Path(tempfile.mkdtemp(prefix="zaiko_cleanup_"))
        (tmp / "server.ipynb").write_text(json.dumps({
            "cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": ["print('cleared')\n"]}],
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 5,
        }), encoding="utf-8")
        (tmp / "kernel-metadata.json").write_text(json.dumps({
            "id": kernel_ref, "title": slug, "code_file": "server.ipynb", "language": "python",
            "kernel_type": "notebook", "is_private": True, "enable_gpu": False, "enable_internet": False,
            "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": [],
        }), encoding="utf-8")
        subprocess.run(["kaggle", "kernels", "push", "-p", str(tmp)], env=env, capture_output=True, text=True, check=False, timeout=30)
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass


def build_server_source(username):
    raw_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/queue/{username}.json"
    src = '''import json, time, base64, subprocess, sys, urllib.request
from pathlib import Path
OUT = Path("/kaggle/working")
LOGS = []

def write_status(phase, message, extra=None):
    d = {"phase": phase, "message": message, "logs": LOGS[-12:]}
    if extra: d.update(extra)
    (OUT/"server_status.json").write_text(json.dumps(d), encoding="utf-8")

def log(msg):
    LOGS.append(msg)
    print(msg, flush=True)
    write_status("installing", msg)

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
    print("Server ready. Waiting for jobs...", flush=True)
    processed = set()
    started = time.time()
    while True:
        q = fetch_queue()
        if q is None:
            time.sleep(5); continue
        if q.get("stop"):
            write_status("stopped", "Disconnected by user")
            break
        for job in q.get("jobs", []):
            jid = job.get("job_id")
            if not jid or jid in processed:
                continue
            processed.add(jid)
            try:
                voice_path = OUT / f"voice_{jid}.wav"
                voice_path.write_bytes(base64.b64decode(job["voice_b64"]))
                audio_path = OUT / f"generated_{jid}.wav"
                class LiveProgress:
                    def tqdm(self, iterable, *a, **kw):
                        items = list(iterable); total = len(items)
                        for i, item in enumerate(items, 1):
                            yield item
                            pct = (i/total)*100.0 if total else 100.0
                            (OUT/f"status_{jid}.json").write_text(json.dumps({"percent": pct, "message": f"chunk {i}/{total}"}), encoding="utf-8")
                (OUT/f"status_{jid}.json").write_text(json.dumps({"percent": 1, "message": "starting"}), encoding="utf-8")
                tts.infer(ref_file=str(voice_path), ref_text="", gen_text=job["text"], progress=LiveProgress(), file_wave=str(audio_path), remove_silence=False)
                (OUT/f"status_{jid}.json").write_text(json.dumps({"percent": 100, "message": "done", "complete": True}), encoding="utf-8")
            except Exception as exc:
                (OUT/f"status_{jid}.json").write_text(json.dumps({"percent": 0, "message": str(exc), "error": True}), encoding="utf-8")
        if time.time() - started > 6*3600:
            write_status("stopped", "Session time limit reached")
            break
        time.sleep(5)
except Exception as exc:
    write_status("error", repr(exc))
'''
    return src.replace("__RAW_URL__", raw_url)


def _poll_for_ready(username, job_id, kernel_ref, env, report, enforce_queue_timeout):
    """Poll an already-pushed/-running kernel for its server_status.json.
    If enforce_queue_timeout is True, also watches Kaggle's own queued/running
    state and triggers the scoped cleanup after QUEUE_TIMEOUT_SECONDS stuck in
    'queued'. Returns True once connected, False on any terminal outcome."""
    queued_since = None
    for _ in range(240):
        if enforce_queue_timeout:
            k_status = kaggle_kernel_status(kernel_ref, env)
            if k_status == "queued":
                queued_since = queued_since or time.time()
                if time.time() - queued_since > QUEUE_TIMEOUT_SECONDS:
                    _cleanup_stuck_kernel(kernel_ref, env)
                    report(
                        status="failed",
                        error="This server instance stayed queued on Kaggle for over 5 minutes, "
                              "so only that stuck instance was reset (no other notebooks were touched). "
                              "Please try Connect again.",
                        progress=0,
                    )
                    return False
            elif k_status == "running":
                queued_since = None
        probe_dir = Path(tempfile.mkdtemp(prefix="zaiko_probe_"))
        try:
            subprocess.run(["kaggle", "kernels", "output", kernel_ref, "-p", str(probe_dir), "-o", "-q"], env=env, capture_output=True, text=True, check=False, timeout=30)
            status_files = list(probe_dir.rglob("server_status.json"))
            if status_files:
                payload = json.loads(status_files[0].read_text(encoding="utf-8"))
                phase = payload.get("phase"); logs = payload.get("logs", [])
                if phase == "ready":
                    report(status="connected", message="Connected", progress=100, logs=logs)
                    return True
                if phase == "error":
                    report(status="failed", error=payload.get("message", "Server failed to start."), logs=logs)
                    return False
                if phase == "stopped":
                    report(status="disconnected", message=payload.get("message", "Disconnected"), logs=logs)
                    return False
                report(status="installing", message=payload.get("message", "Installing..."), progress=min(90, 15 + len(logs) * 6), logs=logs)
            elif enforce_queue_timeout and k_status == "queued":
                queue_msg = "Kaggle Cloud Scheduler: Notebook is currently Queued on servers (Chup hai / waiting for free GPU cluster)..."
                report(status="installing", message=queue_msg, progress=10, logs=[queue_msg])
        except Exception:
            pass
        finally:
            shutil.rmtree(probe_dir, ignore_errors=True)
        time.sleep(4)
    report(status="failed", error="The server took too long to start. Please try again.")
    return False


def run_connect_job(username, job_id, gen_username, gen_token):
    def report(**fields):
        update_job(username, job_id, **fields)
    workspace = None
    try:
        ensure_queue(username)
        kernel_slug = re.sub(r"[^a-z0-9-]", "-", f"zaiko-srv-{username.lower()}").strip("-")[:80]
        kernel_ref = f"{gen_username}/{kernel_slug}"
        env = os.environ.copy(); env["KAGGLE_USERNAME"] = gen_username; env["KAGGLE_API_TOKEN"] = gen_token; env["KAGGLE_KEY"] = gen_token

        report(status="connecting", message="Checking for an existing server...", progress=5, kernel_ref=kernel_ref, logs=[])

        # Reuse an already-running instance for this user instead of pushing a
        # brand-new one (same deterministic kernel id per user => this never
        # creates or affects any other notebook on the account).
        if kaggle_kernel_status(kernel_ref, env) == "running":
            if _poll_for_ready(username, job_id, kernel_ref, env, report, enforce_queue_timeout=False):
                return

        workspace = Path(tempfile.mkdtemp(prefix="zaiko_srv_"))
        notebook_path = workspace / "server.ipynb"
        metadata_path = workspace / "kernel-metadata.json"
        source = build_server_source(username)
        notebook = {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source.splitlines(True)}], "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
        notebook_path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
        # NOTE: enable_gpu only requests *a* GPU. Kaggle's public kernel-metadata.json
        # schema has no documented field to force a specific accelerator (e.g. "T4 x2") -
        # Kaggle assigns whichever GPU is available on the account, so this can't be
        # guaranteed from here.
        metadata = {"id": kernel_ref, "title": kernel_slug, "code_file": "server.ipynb", "language": "python", "kernel_type": "notebook", "is_private": True, "enable_gpu": True, "enable_internet": True, "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": []}
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        report(status="connecting", message="Connecting to server...", progress=10)
        pushed = subprocess.run(["kaggle", "kernels", "push", "-p", str(workspace)], env=env, capture_output=True, text=True, check=False)
        if pushed.returncode != 0:
            report(status="failed", error="Could not start the server. Please check your generation credentials.")
            return
        report(status="installing", message="Server starting, installing dependencies...", progress=15)
        _poll_for_ready(username, job_id, kernel_ref, env, report, enforce_queue_timeout=True)
    except FileNotFoundError:
        update_job(username, job_id, status="failed", error="The generation service is not available right now.")
    except Exception:
        update_job(username, job_id, status="failed", error="Something went wrong while connecting. Please try again.")
    finally:
        if workspace:
            shutil.rmtree(workspace, ignore_errors=True)


def start_connection(username, gen_username, gen_token):
    jid = create_job(username, "connect", {})
    threading.Thread(target=run_connect_job, args=(username, jid, gen_username, gen_token), daemon=True).start()
    return jid


def disconnect_connection(username, jid):
    push_stop_flag(username)
    update_job(username, jid, status="disconnected", message="Disconnecting... this can take up to a minute while the server winds down.")


def run_tts_poll(username, job_id, kernel_ref, gen_username, gen_token, remote_job_id):
    env = os.environ.copy(); env["KAGGLE_USERNAME"] = gen_username; env["KAGGLE_API_TOKEN"] = gen_token; env["KAGGLE_KEY"] = gen_token
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
                data = audio_files[0].read_bytes()
                result = outputs_dir(username) / f"{job_id}.wav"
                result.write_bytes(data)
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
    ok = push_job_to_queue(username, remote_job_id, text, voice_b64)
    if not ok:
        update_job(username, jid, status="failed", error="Could not reach the server. Please try again.")
        return jid
    threading.Thread(target=run_tts_poll, args=(username, jid, kernel_ref, gen_username, gen_token, remote_job_id), daemon=True).start()
    return jid

# -------------------- CREDITS --------------------

def charge_once(db, profile, username, jid, chars):
    job = get_job(username, jid)
    if not job or job.get("credits_charged"):
        return True
    remaining = int(profile.get("remaining_chars", 0)); chars = int(chars or 0)
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
/* Hide Streamlit's own chrome (menu, deploy button, footer badge, rainbow decoration) */
#MainMenu{visibility:hidden!important;height:0!important;}
footer{visibility:hidden!important;height:0!important;}
.stDeployButton{display:none!important;}
[data-testid="stDecoration"]{display:none!important;}
header[data-testid="stHeader"]{background:transparent!important;height:0!important;min-height:0!important;}
[data-testid="stSidebar"]{background:#070e1b;border-right:1px solid var(--line)}
.brand{font-weight:900;letter-spacing:.7px;font-size:1.25rem;background:linear-gradient(90deg,#56dcff,#8b7cff,#ff76cf);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.zhead{position:fixed;top:env(safe-area-inset-top,0px);left:0;right:0;z-index:9999;background:rgba(5,10,20,.91);backdrop-filter:blur(18px);border-bottom:1px solid var(--line);padding:14px 22px 14px 60px;min-height:58px;display:flex;align-items:center}
/* Restyle Streamlit's real sidebar toggle as a clean hamburger icon, aligned with the fixed header.
   (Note: on Streamlit Community Cloud, the app's OWNER also sees a separate platform toolbar —
   Share/star/manage-app — above and below the app itself; that is hosting chrome outside our
   app's DOM and can't be restyled or hidden from app.py. Regular visitors don't see it.) */
[data-testid="stSidebarCollapsedControl"]{position:fixed!important;top:calc(env(safe-area-inset-top,0px) + 12px)!important;left:16px!important;z-index:10000!important;}
[data-testid="stSidebarCollapsedControl"] svg{display:none!important;}
[data-testid="stSidebarCollapsedControl"]::after{content:"☰";font-size:1.5rem;color:#bfeeff;}
[data-testid="stSidebar"] [data-testid="baseButton-headerNoPadding"] svg{display:none!important;}
[data-testid="stSidebar"] [data-testid="baseButton-headerNoPadding"]::after{content:"☰";font-size:1.3rem;color:#bfeeff;}
.card,.hero{background:linear-gradient(145deg,rgba(14,26,46,.94),rgba(8,18,33,.91));border:1px solid rgba(126,211,255,.12);border-radius:20px;padding:24px;margin-bottom:18px;box-shadow:0 18px 45px rgba(0,0,0,.25)}
.card:hover{border-color:rgba(86,220,255,.22)}.hero h1{margin:0 0 6px}.muted,.small{color:var(--muted)}
.footer{text-align:center;margin-top:48px;padding:28px 10px;color:#8193aa;border-top:1px solid rgba(255,255,255,.07)}
.wa{display:inline-block;margin-top:10px;padding:10px 17px;border-radius:12px;border:1px solid rgba(86,220,255,.28);background:rgba(86,220,255,.08);color:#9eeaff!important;text-decoration:none;font-weight:800}
.login-wrap{max-width:520px;margin:7vh auto}.login-brand{text-align:center;font-size:2rem}.typewriter{min-height:86px;text-align:center;font-size:1.35rem;font-weight:900;line-height:1.45;background:linear-gradient(90deg,#56dcff,#8b7cff,#ff76cf);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:22px 0 26px}
.section-title{font-size:1.1rem;font-weight:800;margin:2px 0 14px}.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#5ff2a8;box-shadow:0 0 12px #5ff2a8;margin-right:7px}
.stButton>button{border-radius:12px;border:1px solid rgba(86,220,255,.18);min-height:44px}.stButton>button:disabled{background:#172238!important;color:#596982!important}
textarea[aria-label="Enter Your Text"]{height:260px!important;max-height:260px!important;overflow-y:auto!important}
[data-testid="stMetric"]{background:rgba(14,26,46,.68);border:1px solid rgba(126,211,255,.10);border-radius:16px;padding:14px}
@media(max-width:760px){.block-container{padding-top:6.5rem}.zhead{padding:10px 12px 10px 52px}.hero,.card{padding:18px;border-radius:16px}.login-wrap{margin:4vh auto}.typewriter{font-size:1.05rem}}
</style>
""", unsafe_allow_html=True)

# -------------------- SESSION STATE --------------------
for k, v in {"auth_session": False, "current_user": "", "session_id": "", "page": "Dashboard", "show_token": False, "settings_form_version": 0}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Public share route works without exposing credentials.
share_token = st.query_params.get("share")
if share_token:
    shared = get_share(share_token)
    if shared:
        _, job = shared
        st.markdown(f'<div class="login-wrap"><div class="login-brand brand">{BRAND}</div><div class="card"><h2>{html.escape(job.get("title","Shared Audio"))}</h2><p class="small">Voice: {html.escape(job.get("voice_name",""))}</p>', unsafe_allow_html=True)
        audio = Path(job["result_file"])
        st.audio(audio.read_bytes(), format="audio/wav")
        st.download_button("Download Audio", audio.read_bytes(), file_name=f'{safe_filename(job.get("title","audio"))}.wav', mime="audio/wav", use_container_width=True)
        st.markdown('</div></div>', unsafe_allow_html=True)
    else:
        st.error("This shared audio link has expired or is no longer available.")
    st.stop()

user_db = fetch_live_database()

# -------------------- AUTH RESTORE --------------------
# Cookies written from inside components.html can be silently blocked by mobile
# Chrome / Streamlit Cloud's sandboxed iframe (third-party cookie policies), so
# the URL's own ?sid= query param is the reliable persistence path; the cookie
# is kept only as a bonus for browsers that do allow it.
if not st.session_state.auth_session:
    sid = cookie_session_id() or st.query_params.get("sid")
    username = resolve_session(sid) if sid else None
    if username and username in user_db and not user_db[username].get("is_revoked", False):
        st.session_state.auth_session = True; st.session_state.current_user = username; st.session_state.session_id = sid
        st.query_params["sid"] = sid
        touch_session(sid)


def login_page():
    st.query_params.clear()
    st.markdown(f'''<div class="login-wrap">
      <div class="login-brand brand">{BRAND}</div>
      <div id="typewriter" class="typewriter"></div>
      <div class="card"><h2 style="margin-top:0">Welcome back</h2>''', unsafe_allow_html=True)
    components.html('''<script>
      const lines=["Give Your Words a Voice.","Turn Text Into Natural Speech.","Where Every Word Comes Alive.","Speak. Create. Inspire."];
      let i=0,n=0,del=false; const root=window.parent.document.getElementById('typewriter');
      function tick(){if(!root)return;const s=lines[i];if(!del){n++;root.textContent=s.slice(0,n);if(n===s.length){del=true;setTimeout(tick,1400);return}}else{n--;root.textContent=s.slice(0,n);if(n===0){del=false;i=(i+1)%lines.length}}setTimeout(tick,del?34:62)} tick();
    </script>''', height=0)
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
                # sid in the URL is what actually survives a hard refresh (cookies
                # from components.html get blocked by some mobile browsers); the
                # cookie is set too as a harmless bonus for browsers that allow it.
                st.query_params["page"] = "Dashboard"
                st.query_params["sid"] = sid
                set_cookie(sid, reload=False)
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    msg = quote(f"Hi {ADMIN_CONTACT_NAME}, I want to request access to {BRAND}.")
    st.markdown(f'''<div class="card" style="text-align:center"><div style="font-weight:800">Need access?</div><div class="small">{ADMIN_CONTACT_NAME}</div><a class="wa" href="https://wa.me/{WHATSAPP_NUMBER_INTL}?text={msg}" target="_blank">💬 Contact on WhatsApp</a></div></div>''', unsafe_allow_html=True)

if not st.session_state.auth_session:
    login_page(); st.stop()

active_username = st.session_state.current_user
if active_username not in user_db or user_db[active_username].get("is_revoked", False):
    remove_session(st.session_state.session_id); st.session_state.auth_session = False; st.session_state.current_user = ""; clear_cookie(); st.stop()
profile = user_db[active_username]; is_admin = bool(profile.get("is_admin", False)); valid_pages = ADMIN_PAGES if is_admin else CLIENT_PAGES
requested_page = st.query_params.get("page")
if requested_page in valid_pages:
    st.session_state.page = requested_page
if st.session_state.page not in valid_pages:
    st.session_state.page = valid_pages[0]
page = st.session_state.page


def goto(p):
    st.session_state.page = p; st.query_params["page"] = p; st.rerun()


def logout():
    remove_session(st.session_state.get("session_id", ""))
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.query_params.clear(); clear_cookie()


def expiry_dt():
    try:
        return datetime.strptime(profile.get("expiry_timestamp", ""), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now()


def header():
    st.markdown(f'<div class="zhead"><span class="brand">{BRAND}</span></div>', unsafe_allow_html=True)


def metric_boxes():
    total = int(profile.get("total_credits_allocated", profile.get("total_limit", 0))); rem = int(profile.get("remaining_chars", 0)); exp = expiry_dt()
    left = max(0, int((exp - datetime.now()).total_seconds())); d, left = divmod(left, 86400); h, left = divmod(left, 3600); m, s = divmod(left, 60)
    a, b, c = st.columns(3)
    a.metric("Total Credits", f"{total:,}")
    b.metric("Remaining Credits", f"{rem:,}")
    with c:
        st.markdown(f'<div class="small">Plan Expiry</div><div style="font-weight:800" id="expiry-count">{d} Days {h} Hours {m} Minutes {s} Seconds</div>', unsafe_allow_html=True)
    iso = exp.isoformat()
    components.html(f'''<script>
    const ex=new Date("{iso}"); function t(){{let x=Math.max(0,Math.floor((ex-new Date())/1000));let d=Math.floor(x/86400);x%=86400;let h=Math.floor(x/3600);x%=3600;let m=Math.floor(x/60),s=x%60;let e=window.parent.document.getElementById('expiry-count');if(e)e.textContent=`${{d}} Days ${{h}} Hours ${{m}} Minutes ${{s}} Seconds`;}}t();setInterval(t,1000);
    </script>''', height=0)


def nav():
    with st.sidebar:
        st.markdown(f'<div class="brand" style="font-size:1.35rem">{BRAND}</div>', unsafe_allow_html=True)
        st.caption(active_username.title())
        st.divider()
        for item in valid_pages:
            label = f'{PAGE_ICONS.get(item,"•")}  {item}'
            if st.button(label, use_container_width=True, key="nav_" + item, type="primary" if item == page else "secondary"):
                goto(item)
        st.divider()
        if st.button("Logout", use_container_width=True, key="logout_btn"):
            logout(); st.stop()
    # Best-effort auto-close: once a nav button inside the sidebar is clicked,
    # collapse the sidebar shortly after. Streamlit doesn't expose an official
    # API for this, so the selectors below may need small updates if a future
    # Streamlit version renames these internal test-ids.
    components.html('''<script>
    (function(){
      const doc = window.parent.document;
      function collapseSidebar(){
        const btn = doc.querySelector('[data-testid="stSidebar"] [data-testid="baseButton-headerNoPadding"]')
                  || doc.querySelector('[data-testid="stSidebarCollapsedControl"]');
        if (btn) btn.click();
      }
      const sidebar = doc.querySelector('[data-testid="stSidebar"]');
      if (sidebar && !sidebar.dataset.zaikoBound) {
        sidebar.dataset.zaikoBound = "1";
        sidebar.addEventListener('click', function(e){
          const el = e.target.closest('button');
          if (el && !el.closest('[data-testid="baseButton-headerNoPadding"]')) {
            setTimeout(collapseSidebar, 250);
          }
        });
      }
    })();
    </script>''', height=0)


def footer():
    msg = quote(f"Hi, I want to know more about {BRAND}.")
    st.markdown(f'''<div class="footer"><div class="brand">{BRAND}</div><div class="small">{FOOTER_BY}</div><a class="wa" href="https://wa.me/{WHATSAPP_NUMBER_INTL}?text={msg}" target="_blank">💬 Contact on WhatsApp</a></div>''', unsafe_allow_html=True)

# -------------------- PAGE RENDERERS --------------------

def page_dashboard():
    header()
    st.markdown(f'<div class="hero"><h1>Welcome back, {html.escape(active_username.title())}</h1><p class="muted"><span class="status-dot"></span>Your creative workspace is ready.</p></div>', unsafe_allow_html=True)
    metric_boxes()
    if st.button("Start Voice Cloning", type="primary", use_container_width=True):
        goto("Voice Cloning")
    footer()


def page_voice_cloning():
    header(); st.markdown("## Voice Cloning"); st.caption("Save a short reference voice under a name you will recognize.")
    st.markdown('<div class="card">', unsafe_allow_html=True)
    name = st.text_input("Voice Name", placeholder="e.g. Guru Ji", max_chars=80, key="vc_name")
    st.caption("Give your saved voice a simple name or label.")
    up = st.file_uploader("Upload Reference Voice", type=[x.lstrip('.') for x in SUPPORTED_VOICE_EXT], key="vc_upload")
    st.caption("Maximum duration: 12 seconds for better results • Supported: WAV, MP3, M4A, OGG, FLAC")
    if up:
        suffix = Path(up.name).suffix.lower(); dur = uploaded_audio_duration(up)
        if suffix not in SUPPORTED_VOICE_EXT:
            st.error("Please upload an audio file in a supported format.")
        else:
            detail = f"{up.name} • {up.size/1024:.1f} KB"
            if dur is not None:
                detail += f" • {dur:.2f}s"
            st.caption(detail)
            if dur is not None and dur > MAX_VOICE_SECONDS:
                st.error("Please upload a voice sample of 12 seconds or less.")
    saving = st.session_state.get("vc_saving", False)
    if st.button("Save Voice Clone", type="primary", use_container_width=True, disabled=saving):
        clean = name.strip()
        dur = uploaded_audio_duration(up) if up else None
        if not clean:
            st.error("Please enter a voice name.")
        elif not up:
            st.error("Please upload a voice file.")
        elif dur is not None and dur > MAX_VOICE_SECONDS:
            st.error("Please upload a voice sample of 12 seconds or less.")
        else:
            st.session_state.vc_saving = True; bar = st.progress(0); msg = st.empty(); msg.info("Preparing..."); bar.progress(15); time.sleep(.12); msg.info("Uploading..."); bar.progress(65); time.sleep(.12)
            ext = Path(up.name).suffix.lower(); dest = voice_dir(active_username) / (safe_filename(clean) + ext); dest.write_bytes(up.getbuffer()); msg.info("Saving..."); bar.progress(100); st.session_state.vc_saving = False; st.success(f'Voice "{clean}" saved successfully.'); time.sleep(.2); st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("### My Voices")
    vs = saved_voices(active_username)
    if not vs:
        st.info("Upload Your First Voice")
    for v in vs:
        st.markdown('<div class="card">', unsafe_allow_html=True); a, b = st.columns([4, 1]); a.markdown(f"**{html.escape(v.stem)}**"); b1 = b.button("Delete", key="del_" + v.name)
        try:
            a.audio(v.read_bytes(), format="audio/" + v.suffix.lstrip('.'))
        except Exception:
            pass
        confirm = "confirm_" + v.name
        if b1:
            st.session_state[confirm] = True
        if st.session_state.get(confirm):
            st.warning(f'Delete "{v.stem}"? This voice sample will be permanently removed.')
            c1, c2 = st.columns(2)
            if c1.button("Cancel", key="cancel_" + v.name):
                st.session_state[confirm] = False; st.rerun()
            if c2.button("Delete", key="confirm_" + v.name):
                v.unlink(missing_ok=True); st.session_state[confirm] = False; st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    footer()


def process_completed_jobs():
    jobs = all_jobs(active_username); completed = [j for j in jobs if j.get("type") == "tts" and j.get("status") == "completed"]
    for job in completed:
        if not job.get("credits_charged"):
            if not charge_once(user_db, profile, active_username, job["job_id"], job.get("chars", 0)):
                update_job(active_username, job["job_id"], status="failed", error="Your credits could not be updated. Please contact support."); continue
        if not job.get("history_recorded") and job.get("result_file") and Path(job["result_file"]).exists():
            add_history(active_username, {"job_id": job["job_id"], "title": job.get("title", "Untitled"), "voice_name": job.get("voice_name", ""), "audio_path": job["result_file"], "generated_at": datetime.now().isoformat()})
            update_job(active_username, job["job_id"], history_recorded=True)


def result_card(job):
    result = Path(job.get("result_file", ""))
    if not result.exists():
        return
    st.markdown('<div class="card">', unsafe_allow_html=True); st.success("Speech generated successfully."); st.markdown(f"### {html.escape(job.get('title','Untitled'))}"); st.caption(f"Voice: {html.escape(job.get('voice_name',''))}")
    audio = result.read_bytes(); st.audio(audio, format="audio/wav")
    a, b = st.columns(2); a.download_button("Download", audio, file_name=f'{safe_filename(job.get("title","audio"))}.wav', mime="audio/wav", use_container_width=True, key="download_" + job["job_id"])
    token = create_share(active_username, job["job_id"])
    if token:
        try:
            base = st.context.url
        except Exception:
            base = ""
        if base:
            share_url = base.split("?")[0] + "?share=" + token
            if b.button("Share", use_container_width=True, key="share_" + job["job_id"]):
                st.session_state["share_url"] = share_url
        if st.session_state.get("share_url"):
            st.text_input("Shareable link", value=st.session_state["share_url"], key="share_link_display")
            st.caption("Share links expire after 7 days.")
    st.markdown('</div>', unsafe_allow_html=True)


def page_tts():
    header(); st.markdown("## Turn Your Text Into Speech"); st.caption("Transform your text into natural, expressive speech using your selected voice.")
    vs = saved_voices(active_username)
    if not vs:
        st.warning("No saved voice found. Add one in Voice Cloning first.")
        if st.button("Open Voice Cloning", use_container_width=True):
            goto("Voice Cloning")
        footer(); return

    gen_user = str(profile.get("kaggle_username", "")).strip(); gen_token = str(profile.get("kaggle_token", "")).strip()
    conn = latest_job(active_username, "connect")
    conn_status = conn.get("status") if conn else None
    is_connecting = conn_status in {"connecting", "installing"}
    is_connected = conn_status == "connected"

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### Server Connection")
    if not gen_user or not gen_token:
        st.warning("Please connect your generation account in Settings before using the server.")
    else:
        if is_connected:
            st.success("● Connected — server is ready.")
            if st.button("Disconnect", use_container_width=True):
                disconnect_connection(active_username, conn["job_id"]); st.rerun()
        elif is_connecting:
            pct = float(conn.get("progress", 5))
            st.progress(int(pct))
            st.caption(conn.get("message", "Connecting..."))
            for line in (conn.get("logs") or [])[-6:]:
                st.text(line)
            time.sleep(1.5); st.rerun()
        else:
            if conn_status == "failed":
                st.error(conn.get("error") or "Could not connect. Please try again.")
            if conn_status == "disconnected":
                st.caption(conn.get("message", "Disconnected."))
            if st.button("Connect to Server", type="primary", use_container_width=True):
                start_connection(active_username, gen_user, gen_token); st.rerun()
        st.caption("Disconnecting stops the server within roughly a minute, so GPU hours aren't wasted while idle.")
    st.markdown('</div>', unsafe_allow_html=True)

    active = active_job(active_username, "tts")
    names = [v.stem for v in vs]
    active_voice = active.get("voice_name") if active else st.session_state.get("tts_voice", names[0])
    idx = names.index(active_voice) if active_voice in names else 0
    st.markdown('<div class="card">', unsafe_allow_html=True)
    disabled_inputs = bool(active) or not is_connected
    voice = st.selectbox("Select Your Voice", names, index=idx, disabled=disabled_inputs)
    selected = next(v for v in vs if v.stem == voice)
    text_default = active.get("text", "") if active else st.session_state.get("tts_text", "")
    text = st.text_area("Enter Your Text", value=text_default, height=260, placeholder="Type your text here...", disabled=disabled_inputs, key="tts_text_area")
    if not active:
        st.session_state.tts_text = text; st.session_state.tts_voice = voice
    count = len(text); rem = int(profile.get("remaining_chars", 0))
    a, b = st.columns(2); a.metric("Characters in this script", f"{count:,}"); b.metric("Remaining after generation", f"{max(rem-count,0):,}")
    title_default = active.get("title", "") if active else st.session_state.get("tts_title", "")
    title = st.text_input("Audio Title", value=title_default, placeholder="Technology", disabled=disabled_inputs, key="tts_title_input")
    if not active:
        st.session_state.tts_title = title
    if not is_connected and not active:
        st.caption("Connect to the server above before generating speech.")
    if count > rem and not active:
        st.error("Not enough credits for this script.")
    clicked = st.button("Generate Speech", type="primary", use_container_width=True, disabled=disabled_inputs or count == 0 or count > rem)
    if clicked and not active and is_connected:
        snapshot_title = title.strip() or "Untitled"
        start_generation(active_username, text, snapshot_title, selected, conn["kernel_ref"], gen_user, gen_token, count); st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    if active:
        pct = float(active.get("progress", 0)); st.markdown('<div class="card">', unsafe_allow_html=True); st.progress(int(pct)); st.markdown(f"**{pct:.1f}%** — {html.escape(active.get('message','Generating your speech...'))}"); st.caption("You can safely refresh this page. Your generation will continue."); st.markdown('</div>', unsafe_allow_html=True)
        if active.get("status") == "failed":
            st.error(active.get("error") or "Generation failed. Please try again.")
        else:
            time.sleep(1.2); st.rerun()
    process_completed_jobs()
    jobs = [j for j in all_jobs(active_username) if j.get("type") == "tts" and j.get("status") == "completed" and j.get("result_file")]
    if jobs:
        latest = max(jobs, key=lambda x: x.get("updated", x.get("created", "")))
        result_card(latest)
    footer()


def page_history():
    header()
    items = prune_history(active_username); items.sort(key=lambda x: x.get("generated_at", ""), reverse=True)
    dates = []
    for x in items:
        try:
            dates.append(datetime.fromisoformat(x["generated_at"]).date())
        except Exception:
            pass
    rng = f'{min(dates).strftime("%d %b %Y")} – {max(dates).strftime("%d %b %Y")}' if dates else "No history"
    a, b, c = st.columns(3)
    a.metric("Total Voices Generated", f"{len(items):,}")
    b.metric("Voices Available in History", f"{len(items):,}")
    c.metric("Available History", rng)
    choice = st.radio("Filter", ["Yesterday", "2 Days", "7 Days"], index=2, horizontal=True); days = {"Yesterday": 1, "2 Days": 2, "7 Days": 7}[choice]; cutoff = datetime.now() - timedelta(days=days); filtered = []
    for x in items:
        try:
            if datetime.fromisoformat(x["generated_at"]) >= cutoff:
                filtered.append(x)
        except Exception:
            pass
    if not filtered:
        st.info("No history in this range.")
    else:
        current = None; now = datetime.now()
        for item in filtered:
            ts = datetime.fromisoformat(item["generated_at"]); heading = "Today" if ts.date() == now.date() else ("Yesterday" if ts.date() == (now - timedelta(days=1)).date() else ts.strftime("%d %b %Y"))
            if heading != current:
                st.markdown(f"#### {heading}"); current = heading
            st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown(f"**{html.escape(item.get('title','Untitled'))}**"); st.caption(f"Voice: {html.escape(item.get('voice_name',''))} • Generated: {ts.strftime('%d %b %Y • %I:%M %p')}")
            audio = Path(item.get("audio_path", ""))
            if audio.exists():
                data = audio.read_bytes(); st.audio(data, format="audio/wav"); a, b = st.columns(2); a.download_button("Download", data, file_name=f'{safe_filename(item.get("title","audio"))}.wav', mime="audio/wav", key="hist_dl_" + item.get("job_id", uuid.uuid4().hex))
                token = create_share(active_username, item.get("job_id")) if item.get("job_id") else None
                if token:
                    try:
                        base = st.context.url; url = base.split("?")[0] + "?share=" + token
                    except Exception:
                        url = ""
                    if url and b.button("Share", key="hist_share_" + item.get("job_id", uuid.uuid4().hex)):
                        st.session_state["history_share_url"] = url
                    if st.session_state.get("history_share_url"):
                        st.text_input("Shareable link", value=st.session_state["history_share_url"], key="hist_share_url")
            else:
                st.caption("This audio is no longer available.")
            st.markdown('</div>', unsafe_allow_html=True)
    footer()


def page_settings():
    header(); st.markdown("## Settings"); st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown("### Generation Connection"); st.caption("Connect the account used to power your generations.")
    saved_u = profile.get("kaggle_username", ""); saved_t = profile.get("kaggle_token", "")
    ver = st.session_state.get("settings_form_version", 0)
    show = st.checkbox("Show token", value=st.session_state.get("show_token", False)); st.session_state.show_token = show
    with st.form(f"connection_form_{ver}"):
        u = st.text_input("Username", value=saved_u, key=f"conn_user_{ver}")
        t = st.text_input("API Token", value=saved_t, type="default" if show else "password", key=f"conn_token_{ver}")
        a, b, c = st.columns(3); save = a.form_submit_button("Save Credentials", use_container_width=True); verify = b.form_submit_button("Verify Credentials", use_container_width=True); remove = c.form_submit_button("Remove Credentials", use_container_width=True)
    if save:
        if not u.strip() or not t.strip():
            st.error("✕ Unable to save credentials. Please check your details and try again.")
        elif (profile.update({"kaggle_username": u.strip(), "kaggle_token": t.strip()}) or True) and push_database_updates(user_db):
            st.session_state.settings_form_version = ver + 1
            st.success("✓ Credentials saved successfully."); st.rerun()
        else:
            st.error("✕ Unable to save credentials. Please check your details and try again.")
    if verify:
        with st.spinner("Verifying..."):
            uok, tok, err = verify_generation_credentials(u.strip(), t.strip())
        if err:
            st.warning(err)
        else:
            st.write("✓ Username — Valid" if uok else "✕ Username — Invalid"); st.write("✓ API Token — Valid" if tok else "✕ API Token — Invalid")
            if uok and tok:
                st.success("Credentials verified successfully.")
    if remove:
        st.session_state.confirm_remove = True
    if st.session_state.get("confirm_remove"):
        st.warning("Remove your saved credentials? You will need to enter them again before using voice generation."); a, b = st.columns(2)
        if a.button("Cancel", key="cancel_remove"):
            st.session_state.confirm_remove = False; st.rerun()
        if b.button("Remove", key="remove_confirm"):
            profile["kaggle_username"] = ""; profile["kaggle_token"] = ""
            ok = push_database_updates(user_db)
            st.session_state.confirm_remove = False
            st.session_state.settings_form_version = ver + 1
            if ok:
                st.success("✓ Credentials removed successfully.")
            else:
                st.error("Unable to remove credentials.")
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True); footer()


def page_account():
    header(); st.markdown("## Account")
    st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown("### Account Overview")
    a, b, c, d = st.columns(4)
    a.metric("Username", active_username)
    b.metric("Total Credits", f'{int(profile.get("total_credits_allocated",profile.get("total_limit",0))):,}')
    c.metric("Account Status", "Active")
    d.metric("Remaining Credits", f'{int(profile.get("remaining_chars",0)):,}')
    st.caption(f'Expires: {expiry_dt().strftime("%d %b %Y, %I:%M %p")}')
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown("### Change Password")
    with st.form("change_password"):
        old = st.text_input("Current Password", type="password"); new = st.text_input("New Password", type="password"); change = st.form_submit_button("Change Password", use_container_width=True)
    if change:
        if profile.get("password") != old:
            st.error("Current password is incorrect.")
        elif not new:
            st.error("Please enter a new password.")
        else:
            profile["password"] = new; st.success("Password changed successfully.") if push_database_updates(user_db) else st.error("Unable to change password right now.")
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown("### Where Your Account Is Connected")
    current = st.session_state.get("session_id")
    for s in sessions_for_user(active_username):
        is_current = s["sid"] == current; ua = html.escape(s.get("user_agent", "Unknown browser")); ip = html.escape(s.get("ip", "Unavailable")); last = s.get("last_seen", "—")
        st.markdown(f'<div class="card"><strong>{"This device" if is_current else "Other device"}</strong><div class="small">Browser / OS: {ua}</div><div class="small">IP: {ip}</div><div class="small">Last active: {html.escape(last)}</div></div>', unsafe_allow_html=True)
        if not is_current:
            key = "remove_device_" + s["sid"]
            if st.button("Remove Access", key=key):
                st.session_state["confirm_device"] = s["sid"]
            if st.session_state.get("confirm_device") == s["sid"]:
                st.warning("Remove access from this device? This device will be logged out and its current session will no longer be valid."); a, b = st.columns(2)
                if a.button("Cancel", key="cancel_dev_" + s["sid"]):
                    st.session_state.pop("confirm_device", None); st.rerun()
                if b.button("Remove Access", key="confirm_dev_" + s["sid"]):
                    remove_session(s["sid"]); st.session_state.pop("confirm_device", None); st.rerun()
    st.markdown('</div>', unsafe_allow_html=True); footer()

# -------------------- ADMIN --------------------

def admin_dashboard():
    header(); st.markdown(f"## Welcome, {html.escape(active_username.title())}"); st.caption("Administrator workspace")
    regular = [x for x in user_db.values() if not x.get("is_admin", False)]; active = sum(1 for x in regular if not x.get("is_revoked", False)); a, b = st.columns(2); a.metric("Total Clients", len(regular)); b.metric("Active Clients", active); footer()


def admin_registry():
    header(); st.markdown("## Active Users Registry")
    for n, x in [(n, x) for n, x in user_db.items() if not x.get("is_admin", False)]:
        with st.expander(f'{n} — {"Revoked" if x.get("is_revoked") else "Active"}'):
            current = int(x.get("remaining_chars", 0)); add = st.number_input("Add Credits", min_value=0, value=0, key="add_" + n); new_exp_days = st.number_input("Extend Plan Days", min_value=0, value=0, key="days_" + n)
            st.caption(f'Current remaining: {current:,} • Cumulative allocated: {int(x.get("total_credits_allocated",x.get("total_limit",0))):,}')
            a, b = st.columns(2)
            if a.button("Revoke / Grant", key="toggle_" + n, use_container_width=True):
                x["is_revoked"] = not x.get("is_revoked", False); push_database_updates(user_db); st.rerun()
            if b.button("Save Changes", key="save_" + n, use_container_width=True):
                if add:
                    x["remaining_chars"] = current + int(add); x["total_credits_allocated"] = int(x.get("total_credits_allocated", x.get("total_limit", 0))) + int(add); x["total_limit"] = x["total_credits_allocated"]
                if new_exp_days:
                    e = expiry_dt() if n == active_username else datetime.strptime(x["expiry_timestamp"], "%Y-%m-%d %H:%M:%S"); x["expiry_timestamp"] = (max(e, datetime.now()) + timedelta(days=int(new_exp_days))).strftime("%Y-%m-%d %H:%M:%S")
                if push_database_updates(user_db):
                    st.rerun()
    footer()


def admin_deploy():
    header(); st.markdown("## Deploy New Client")
    with st.form("deploy_form"):
        u = st.text_input("New Client Username").upper().strip(); pw = st.text_input("Set Login Password", type="password"); days = st.number_input("Plan Duration (Days)", min_value=1, value=30); chars = st.number_input("Character Allocation", min_value=1000, value=1000000); go = st.form_submit_button("Deploy User", type="primary", use_container_width=True)
    if go:
        if not u or not pw:
            st.error("Username and password are required.")
        elif u in user_db:
            st.error("That username already exists.")
        else:
            amount = int(chars); user_db[u] = {"password": pw, "expiry_timestamp": (datetime.now() + timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S"), "total_limit": amount, "total_credits_allocated": amount, "remaining_chars": amount, "is_revoked": False, "is_admin": False, "kaggle_username": "", "kaggle_token": ""}
            if push_database_updates(user_db):
                st.success(f"User {u} created successfully."); st.rerun()
            else:
                st.error("We couldn't create the account right now.")
    footer()


def admin_settings():
    header(); st.markdown("## Settings"); st.info("Core storage configuration is managed securely outside this interface."); footer()

# -------------------- ROUTER --------------------
nav()
if is_admin:
    routes = {"Dashboard": admin_dashboard, "Active Users Registry": admin_registry, "Deploy New Client": admin_deploy, "Settings": admin_settings}
else:
    routes = {"Dashboard": page_dashboard, "Voice Cloning": page_voice_cloning, "Text To Speech": page_tts, "History": page_history, "Settings": page_settings, "Account": page_account}

routes.get(page, routes[valid_pages[0]])()
