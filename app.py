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
import select
import html
import sys
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
# Backend/provider names are intentionally not exposed in the normal UI.
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
ADMIN_CONTACT_NAME = "Muhammad Zukriya"
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


def _hydrate_database_voices(users):
    for username, info in users.items():
        voices = info.get("voices") or {}
        if not isinstance(voices, dict):
            continue
        folder = voice_dir(username)
        for voice_key, item in voices.items():
            if not isinstance(item, dict):
                continue
            filename = safe_filename(item.get("filename") or voice_key)
            data = item.get("data")
            if not data:
                continue
            try:
                raw = base64.b64decode(data, validate=True)
                target = folder / filename
                if not target.exists() or target.read_bytes() != raw:
                    target.write_bytes(raw)
            except Exception:
                continue
    return users


def _database_voice_payload(path: Path):
    raw = path.read_bytes()
    return {"name": path.stem, "filename": path.name, "data": base64.b64encode(raw).decode("ascii"), "updated": datetime.now().isoformat()}


def _github_db_read(headers):
    r = requests.get(GITHUB_API_URL, headers=headers, timeout=20)
    if r.status_code != 200:
        return None, None
    remote = r.json()
    try:
        db = json.loads(base64.b64decode(remote.get("content", "")).decode("utf-8"))
    except Exception:
        return None, None
    return remote, db


def _github_db_write(headers, remote, db, message):
    body = {"message": message, "content": base64.b64encode(json.dumps(db, indent=2, ensure_ascii=False).encode("utf-8")).decode("ascii"), "sha": remote.get("sha")}
    out = requests.put(GITHUB_API_URL, headers=headers, json=body, timeout=30)
    return out.status_code in (200, 201)


def save_voice_to_database(username, path: Path):
    if not GITHUB_PAT_TOKEN or not path.exists():
        return False
    headers={"Authorization":f"Bearer {GITHUB_PAT_TOKEN}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"ZAIKO-AI-STUDIO"}
    try:
        remote, db = _github_db_read(headers)
        if not remote or not db or username not in db.get("users",{}):
            return False
        user=db["users"][username]
        voices=user.setdefault("voices",{})
        voices[path.stem]=_database_voice_payload(path)
        return _github_db_write(headers, remote, db, f"Save voice sample for {username}")
    except Exception:
        return False


def delete_voice_from_database(username, voice_stem):
    if not GITHUB_PAT_TOKEN:
        return False
    headers={"Authorization":f"Bearer {GITHUB_PAT_TOKEN}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28","User-Agent":"ZAIKO-AI-STUDIO"}
    try:
        remote, db = _github_db_read(headers)
        if not remote or not db or username not in db.get("users",{}):
            return False
        user=db["users"][username]
        voices=user.get("voices") or {}
        voices.pop(voice_stem,None)
        user["voices"]=voices
        return _github_db_write(headers, remote, db, f"Delete voice sample for {username}")
    except Exception:
        return False


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
    """Fetch the account DB without turning a temporary GitHub failure into logout.

    A successful DB snapshot is kept in the current Streamlit session. If GitHub
    is temporarily unavailable, that snapshot is used instead of falling back to
    the admin-only database. The latter was the reason page navigation could
    suddenly make a valid client appear logged out.
    """
    try:
        cache_buster = int(time.time() // 5)
        r = requests.get(f"{DB_URL}?v={cache_buster}", timeout=15)
        if r.status_code == 200:
            users = r.json().get("users", {})
            if users:
                for info in users.values():
                    info.setdefault("total_credits_allocated", int(info.get("total_limit", 0)))
                users = _hydrate_database_voices(users)
                st.session_state["_user_db_cache"] = users
                return users
    except Exception:
        pass

    cached = st.session_state.get("_user_db_cache")
    if isinstance(cached, dict) and cached:
        return cached

    return _hydrate_database_voices(fallback_database())


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


def set_cookie(sid, max_age_days=30, redirect_page="Dashboard"):
    # Cookie is written by the parent document rather than the component iframe.
    # A small, same-origin script is used so normal navigation keeps the session.
    safe_page = quote(redirect_page)
    components.html(
        f"""<script>
        (function() {{
          try {{
            const c = "zaiko_session={sid}; Path=/; Max-Age={max_age_days * 86400}; SameSite=Lax";
            if (window.parent && window.parent.document) window.parent.document.cookie = c;
            document.cookie = c;
          }} catch (e) {{}}
        }})();
        </script>""",
        height=0,
    )


def clear_cookie():
    components.html(
        """<script>
        try {
          const c="zaiko_session=; Path=/; Max-Age=0; SameSite=Lax";
          if(window.parent && window.parent.document) window.parent.document.cookie=c;
          document.cookie=c;
        } catch(e) {}
        </script>""",
        height=0,
    )


def cookie_session_id():
    try:
        value = st.context.cookies.get("zaiko_session")
        return value or None
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
    active = [j for j in jobs if j.get("status") not in {"completed", "failed", "cancelled"}]
    if job_type:
        active = [j for j in active if j.get("type") == job_type]
    return max(active, key=lambda x: x.get("updated", "")) if active else None


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

# -------------------- SERVER CONNECTION --------------------

def _kaggle_env(username, token):
    env = os.environ.copy()
    env["KAGGLE_USERNAME"] = str(username).strip()
    env["KAGGLE_API_TOKEN"] = str(token).strip()
    env["KAGGLE_KEY"] = str(token).strip()
    return env


def _kaggle_internal_post(token, method, payload):
    try:
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "ZAIKO-AI-STUDIO"})
        session.get("https://www.kaggle.com/", timeout=20)
        xsrf = session.cookies.get("XSRF-TOKEN") or session.cookies.get("CSRF-TOKEN")
        headers = {"X-XSRF-TOKEN": xsrf} if xsrf else {}
        response = session.post(f"https://www.kaggle.com/api/i/{method}", json=payload, headers=headers, timeout=20)
        return response.status_code, response.text
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def get_kaggle_runtime(username, token, kernel_slug):
    code, raw = _kaggle_internal_post(token, "kernels.LegacyKernelsService/GetKernelViewModel", {"authorUserName": username, "kernelSlug": kernel_slug, "tab": "output"})
    if code not in (200, 201):
        return None, "UNKNOWN"
    try:
        payload = json.loads(raw)
        kernel = payload.get("kernel") or payload.get("kernelViewModel") or payload
        kernel_id = kernel.get("id") if isinstance(kernel, dict) else None
        if not kernel_id:
            return None, "UNKNOWN"
    except Exception:
        return None, "UNKNOWN"

    code, raw = _kaggle_internal_post(token, "kernels.KernelsService/ListKernelVersions", {"kernelId": kernel_id, "sortOption": "VERSION_ID", "pageSize": 30})
    if code not in (200, 201):
        return None, "UNKNOWN"
    try:
        payload = json.loads(raw)
        items = payload.get("items") or payload.get("versions") or []
        active_words = ("running", "queued", "pending", "initializing", "starting", "active")
        for item in items:
            run = item.get("run") if isinstance(item, dict) else None
            if not isinstance(run, dict):
                continue
            run_status = str(run.get("status") or run.get("state") or "").lower()
            if any(word in run_status for word in active_words):
                session_id = run.get("sessionId") or run.get("session_id") or run.get("id")
                return (str(session_id) if session_id else None), "RUNNING"
        return None, "STOPPED"
    except Exception:
        return None, "UNKNOWN"


def stop_kaggle_session(username, token, kernel_slug):
    session_id, runtime_state = get_kaggle_runtime(username, token, kernel_slug)
    if not session_id:
        return (True, "No active Kaggle runtime session found.") if runtime_state == "STOPPED" else (False, "Could not verify the active Kaggle runtime session.")
    env = _kaggle_env(username, token)
    try:
        cli = subprocess.run(["kaggle", "kernels", "cancel", "--session-id", str(session_id)], env=env, capture_output=True, text=True, timeout=30, check=False)
        if cli.returncode == 0:
            return True, "Kaggle runtime session stopped."
    except Exception:
        pass
    code, raw = _kaggle_internal_post(token, "kernels.KernelsService/CancelKernelSession", {"sessionId": session_id})
    return (True, "Kaggle runtime session stopped.") if code in (200, 201, 202, 204) else (False, raw[-2000:])


def kaggle_kernel_status(kernel_ref, env):
    try:
        r = subprocess.run(["kaggle", "kernels", "status", kernel_ref], env=env, capture_output=True, text=True, timeout=20, check=False)
        combined = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        low = combined.lower()
        if re.search(r"\brunning\b", low): return "running", combined
        if re.search(r"\b(queued|pending|initializing|starting)\b", low): return "queued", combined
        if re.search(r"\b(complete|completed|success|succeeded|stopped|cancelled|canceled)\b", low): return "complete", combined
        if re.search(r"\b(error|failed|failure)\b", low): return "error", combined
        if "not found" in low or "404" in low or "does not exist" in low: return "not_found", combined
        return "unknown", combined
    except subprocess.TimeoutExpired:
        return "unknown", "Kaggle status check timed out."
    except Exception as exc:
        return "unknown", f"{type(exc).__name__}: {exc}"


def kaggle_kernel_logs(kernel_ref, env, timeout=10):
    proc = None
    lines = []
    try:
        proc = subprocess.Popen(["kaggle", "kernels", "logs", kernel_ref, "--follow", "--interval", "1"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        started = time.time()
        while time.time() - started < timeout:
            if proc.stdout is None: break
            ready, _, _ = select.select([proc.stdout], [], [], 0.25)
            if ready:
                line = proc.stdout.readline()
                if line:
                    line = line.rstrip()
                    if line:
                        lines.append(line)
                        if re.search(r"F5[- ]TTS\s+MODEL\s+READY", line, re.I) or re.search(r"SERVER\s+READY", line, re.I) or re.search(r"\[F5-TTS FATAL ERROR\]", line, re.I):
                            break
                elif proc.poll() is not None:
                    break
            elif proc.poll() is not None:
                break
    except Exception as exc:
        lines.append(f"[LOG ERROR] {type(exc).__name__}: {exc}")
    finally:
        if proc is not None:
            try:
                proc.terminate(); proc.wait(timeout=3)
            except Exception:
                try: proc.kill()
                except Exception: pass
    return "\n".join(lines)[-30000:]


def server_file(username):
    return user_dir(username) / "server.json"


def get_server_state(username):
    default = {"status": "disconnected", "progress": 0.0, "message": "Server is not connected.", "kernel": "", "logs": [], "updated": datetime.now().isoformat()}
    return load_json(server_file(username), default)


def set_server_state(username, **fields):
    state = get_server_state(username)
    state.update(fields)
    state["updated"] = datetime.now().isoformat()
    save_json(server_file(username), state)


def _append_server_logs(username, raw_logs):
    if not raw_logs: return
    lines = [x.strip() for x in raw_logs.splitlines() if x.strip()]
    if not lines: return
    state = get_server_state(username)
    old = list(state.get("logs") or [])
    for line in lines:
        if not old or old[-1] != line: old.append(line)
    set_server_state(username, logs=old[-60:])


def build_server_source():
    return """import json, subprocess, sys, time, traceback
from pathlib import Path
STATUS=Path('/kaggle/working/zaiko_server_status.json')
def write_status(state,message,progress=0):
    STATUS.write_text(json.dumps({'status':state,'message':message,'progress':float(progress)},ensure_ascii=False),encoding='utf-8')
def log(message): print(message,flush=True)
try:
    write_status('starting','Starting F5-TTS server...',5); log('[BOOT] ZAIKO F5-TTS server starting...')
    try: subprocess.run(['nvidia-smi'],check=False,timeout=20)
    except Exception as exc: log('[GPU] nvidia-smi check failed: '+repr(exc))
    log('[F5] Installing F5-TTS...')
    subprocess.check_call([sys.executable,'-m','pip','install','-q','f5-tts'])
    write_status('starting','Dependencies installed. Loading F5-TTS model...',55)
    log('[F5] Loading F5-TTS v1 Base model on CUDA...')
    from f5_tts.api import F5TTS
    tts=F5TTS(model='F5TTS_v1_Base',device='cuda')
    log('F5-TTS MODEL READY')
    write_status('ready','F5-TTS model loaded and ready.',100)
    log('SERVER READY'); log('F5-TTS NODE ONLINE')
    while True: time.sleep(20)
except Exception as exc:
    error_text=f'{type(exc).__name__}: {exc}'
    log('[F5-TTS FATAL ERROR] '+error_text)
    traceback.print_exc()
    try: write_status('error',error_text,0)
    except Exception: pass
"""


def start_server_connection(username, gen_username, gen_token):
    state = get_server_state(username)
    if state.get("status") in {"starting", "connected"}: return state
    if not gen_username or not gen_token:
        set_server_state(username,status="error",progress=0,message="Connect your generation credentials in Settings first.")
        return get_server_state(username)
    kernel_slug = re.sub(r"[^a-z0-9-]","-",f"zaiko-server-{username.lower()}").strip("-")[:70]
    set_server_state(username,status="starting",progress=2,message="Preparing your generation server...",kernel=kernel_slug,logs=[])
    threading.Thread(target=run_server_connection,args=(username,kernel_slug,gen_username,gen_token),daemon=True).start()
    return get_server_state(username)


def run_server_connection(username, kernel_slug, gen_username, gen_token):
    workspace=Path(tempfile.mkdtemp(prefix="zaiko_server_")); env=_kaggle_env(gen_username,gen_token); kernel_ref=f"{gen_username}/{kernel_slug}"
    try:
        runtime_id,runtime_state=get_kaggle_runtime(gen_username,gen_token,kernel_slug)
        if runtime_state == "RUNNING" and runtime_id:
            set_server_state(username,status="starting",progress=70,message="Kaggle runtime is already running. Checking live F5-TTS logs...",kernel=kernel_slug)
        else:
            notebook_path=workspace/"server_worker.ipynb"; metadata_path=workspace/"kernel-metadata.json"; source=build_server_source()
            notebook={"cells":[{"cell_type":"code","execution_count":None,"metadata":{},"outputs":[],"source":source.splitlines(True)}],"metadata":{"kernelspec":{"display_name":"Python 3","language":"python","name":"python3"},"language_info":{"name":"python"}},"nbformat":4,"nbformat_minor":5}
            notebook_path.write_text(json.dumps(notebook,indent=2),encoding="utf-8")
            metadata={"id":kernel_ref,"title":kernel_slug,"code_file":"server_worker.ipynb","language":"python","kernel_type":"notebook","is_private":True,"enable_gpu":True,"enable_internet":True,"machine_shape":"NvidiaTeslaT4","dataset_sources":[],"competition_sources":[],"kernel_sources":[],"model_sources":[]}
            metadata_path.write_text(json.dumps(metadata,indent=2),encoding="utf-8")
            set_server_state(username,status="starting",progress=15,message="Submitting the Kaggle GPU session...",kernel=kernel_slug)
            pushed=subprocess.run(["kaggle","kernels","push","-p",str(workspace)],env=env,capture_output=True,text=True,check=False,timeout=120)
            push_output=((pushed.stdout or "")+"\n"+(pushed.stderr or "")).strip(); _append_server_logs(username,push_output)
            if pushed.returncode != 0:
                set_server_state(username,status="error",progress=0,message="The Kaggle F5-TTS session could not be started.",kernel=kernel_slug); return
            set_server_state(username,status="starting",progress=25,message="Kaggle GPU session submitted. Waiting for runtime...",kernel=kernel_slug)

        deadline=time.time()+300
        while time.time()<deadline:
            k_status,status_text=kaggle_kernel_status(kernel_ref,env); low_status=status_text.lower()
            if k_status=="running":
                set_server_state(username,status="starting",progress=75,message="GPU is running. Fetching live F5-TTS logs...",kernel=kernel_slug)
                live_logs=kaggle_kernel_logs(kernel_ref,env,timeout=10); _append_server_logs(username,live_logs); combined=(live_logs+"\n"+status_text).strip()
                if re.search(r"F5[- ]TTS\s+MODEL\s+READY",combined,re.I) or re.search(r"SERVER\s+READY",combined,re.I):
                    set_server_state(username,status="connected",progress=100,message="F5-TTS model is connected and ready.",kernel=kernel_slug); return
                if re.search(r"\[F5-TTS FATAL ERROR\]",combined,re.I):
                    set_server_state(username,status="error",progress=0,message="F5-TTS model failed to start. Please try again.",kernel=kernel_slug); return
                probe_dir=Path(tempfile.mkdtemp(prefix="zaiko_server_probe_"))
                try:
                    subprocess.run(["kaggle","kernels","output",kernel_ref,"-p",str(probe_dir),"-o","-q"],env=env,capture_output=True,text=True,check=False,timeout=30)
                    statuses=list(probe_dir.rglob("zaiko_server_status.json"))
                    if statuses:
                        try: payload=json.loads(statuses[0].read_text(encoding="utf-8"))
                        except Exception: payload={}
                        phase=str(payload.get("status","")).lower(); msg=payload.get("message") or "F5-TTS is starting..."; pct=float(payload.get("progress",80))
                        if phase=="ready": set_server_state(username,status="connected",progress=100,message="F5-TTS model is connected and ready.",kernel=kernel_slug); return
                        if phase=="error": set_server_state(username,status="error",progress=0,message="F5-TTS model failed to start. Please try again.",kernel=kernel_slug); return
                        set_server_state(username,status="starting",progress=max(70,min(95,pct)),message=msg,kernel=kernel_slug)
                finally: shutil.rmtree(probe_dir,ignore_errors=True)
            elif k_status=="queued":
                set_server_state(username,status="starting",progress=35,message="Kaggle GPU is queued. Waiting for a runtime...",kernel=kernel_slug)
            elif k_status in {"complete","not_found"}:
                set_server_state(username,status="error",progress=0,message="The Kaggle F5-TTS session stopped before becoming ready.",kernel=kernel_slug); return
            elif k_status=="error":
                set_server_state(username,status="error",progress=0,message="Kaggle reported an error while starting F5-TTS.",kernel=kernel_slug); return
            elif "not found" in low_status or "does not exist" in low_status:
                set_server_state(username,status="error",progress=0,message="The Kaggle F5-TTS notebook could not be found.",kernel=kernel_slug); return
            time.sleep(4)
        set_server_state(username,status="error",progress=0,message="The F5-TTS server took too long to become ready. Please try again.",kernel=kernel_slug)
    except FileNotFoundError:
        set_server_state(username,status="error",progress=0,message="The generation service is not available right now.",kernel=kernel_slug)
    except Exception as exc:
        _append_server_logs(username,f"[CONNECT ERROR] {type(exc).__name__}: {exc}")
        set_server_state(username,status="error",progress=0,message="The generation server could not be started.",kernel=kernel_slug)
    finally: shutil.rmtree(workspace,ignore_errors=True)


def disconnect_server(username, gen_username, gen_token):
    state=get_server_state(username); kernel=str(state.get("kernel") or "").strip(); ok=True
    if kernel and gen_username and gen_token: ok,_=stop_kaggle_session(gen_username,gen_token,kernel)
    if ok:
        set_server_state(username,status="disconnected",progress=0,message="Server disconnected.",kernel=kernel)
    else:
        set_server_state(username,status="error",progress=0,message="Could not safely stop the Kaggle GPU session. Please refresh and try again.",kernel=kernel)

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


def run_generation_job(username, job_id, text, voice_path, gen_username, gen_token):
    def report(pct, msg, status="generating"):
        update_job(username, job_id, progress=float(max(0, min(100, pct))), message=msg, status=status)
    try:
        voice_file = Path(voice_path)
        if not voice_file.exists():
            update_job(username, job_id, status="failed", error="The selected voice is missing. Please re-upload it.")
            return
        if not gen_username or not gen_token:
            update_job(username, job_id, status="failed", error="Generation is not connected yet. Please connect the server first.")
            return
        server=get_server_state(username)
        if server.get("status") != "connected":
            update_job(username, job_id, status="failed", error="Generation server is not connected. Please connect the server first.")
            return

        report(3, "Preparing your request...", "generating")
        voice_b64 = base64.b64encode(voice_file.read_bytes()).decode("ascii")
        text_json = json.dumps(text, ensure_ascii=False)
        kernel_slug = re.sub(r"[^a-z0-9-]", "-", f"zaiko-{username.lower()}-{job_id[:10]}").strip("-")[:80]
        workspace = Path(tempfile.mkdtemp(prefix="zaiko_job_"))
        output_dir = Path(tempfile.mkdtemp(prefix="zaiko_output_"))
        notebook_path = workspace / "active_worker.ipynb"
        metadata_path = workspace / "kernel-metadata.json"

        source = """import base64, json, subprocess, sys, math
from pathlib import Path
OUTPUT=Path('/kaggle/working'); STATUS=OUTPUT/'status.json'; AUDIO=OUTPUT/'generated.wav'; VOICE=OUTPUT/'reference_voice.wav'
TEXT=__TEXT_JSON__; VOICE_B64=__VOICE_B64__
def write_status(status,message='',percent=None):
    d={'status':status,'message':message}
    if percent is not None:d['percent']=float(percent)
    STATUS.write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
try:
    write_status('starting','Preparing engine...',0); VOICE.write_bytes(base64.b64decode(VOICE_B64)); subprocess.check_call([sys.executable,'-m','pip','install','-q','f5-tts'])
    from f5_tts.api import F5TTS
    import numpy as np, soundfile as sf
    tts=F5TTS(model='F5TTS_v1_Base',device='cuda')
    chunk_size=400
    chunks=[TEXT[i:i+chunk_size] for i in range(0,len(TEXT),chunk_size)] or ['']
    total=len(chunks); parts=[]; sample_rate=None
    for i,chunk in enumerate(chunks,1):
        part=OUTPUT/f'part_{i:05d}.wav'
        pct=((i-1)/total)*88.0
        write_status('generating',f'Generating batch {i}/{total}...',pct)
        tts.infer(ref_file=str(VOICE),ref_text='',gen_text=chunk,file_wave=str(part),remove_silence=False)
        data,rate=sf.read(str(part),dtype='float32')
        if sample_rate is None: sample_rate=rate
        parts.append(data)
        pct=(i/total)*88.0
        write_status('generating',f'Batch {i}/{total} complete.',pct)
    write_status('finishing','Combining generated batches...',94)
    audio=np.concatenate(parts) if parts else np.array([],dtype='float32')
    sf.write(str(AUDIO),audio,sample_rate or 24000)
    if not AUDIO.exists() or AUDIO.stat().st_size<1000: raise RuntimeError('No valid audio was produced.')
    write_status('success','Audio generated successfully.',100); print('GENERATION COMPLETE 100.0%',flush=True)
except Exception as exc:
    write_status('error',repr(exc)); print('GENERATION ERROR:',repr(exc),flush=True)
"""
        source = source.replace("__TEXT_JSON__", text_json).replace("__VOICE_B64__", repr(voice_b64))
        notebook = {"cells":[{"cell_type":"code","execution_count":None,"metadata":{},"outputs":[],"source":source.splitlines(True)}],"metadata":{"kernelspec":{"display_name":"Python 3","language":"python","name":"python3"},"language_info":{"name":"python"}},"nbformat":4,"nbformat_minor":5}
        notebook_path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
        metadata = {"id":f"{gen_username}/{kernel_slug}","title":kernel_slug,"code_file":"active_worker.ipynb","language":"python","kernel_type":"notebook","is_private":True,"enable_gpu":True,"enable_internet":True,"machine_shape":"NvidiaTeslaT4","dataset_sources":[],"competition_sources":[],"kernel_sources":[],"model_sources":[]}
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        env=os.environ.copy(); env["KAGGLE_USERNAME"]=gen_username; env["KAGGLE_API_TOKEN"]=gen_token; env["KAGGLE_KEY"]=gen_token
        report(12,"Preparing generation request...","generating")
        pushed=subprocess.run(["kaggle","kernels","push","-p",str(workspace)],env=env,capture_output=True,text=True,check=False)
        if pushed.returncode!=0:
            update_job(username,job_id,status="failed",error="We couldn't start your generation. Please try again."); return
        report(18,"Generation request started.","generating")
        report(25,"Generating your speech...","generating")
        kernel_ref=f"{gen_username}/{kernel_slug}"
        last_progress=25.0
        for _ in range(240):
            probe_dir=Path(tempfile.mkdtemp(prefix="zaiko_probe_"))
            try:
                probe=subprocess.run(["kaggle","kernels","output",kernel_ref,"-p",str(probe_dir),"-o","-q"],env=env,capture_output=True,text=True,check=False,timeout=30)
                statuses=list(probe_dir.rglob("status.json")); audios=list(probe_dir.rglob("generated.wav"))
                payload=None
                if statuses:
                    try: payload=json.loads(statuses[0].read_text(encoding="utf-8"))
                    except Exception: payload=None
                if payload:
                    pct=float(payload.get("percent",last_progress)); last_progress=max(last_progress,min(90,pct))
                    report(last_progress,"Generating your speech...","generating")
                    if payload.get("status")=="error":
                        update_job(username,job_id,status="failed",error="Generation could not be completed. Please try again."); return
                    if payload.get("status")=="success" and audios: break
                if audios: break
            except Exception:
                pass
            finally: shutil.rmtree(probe_dir,ignore_errors=True)
            time.sleep(3)
        else:
            update_job(username,job_id,status="failed",error="Generation took too long and was stopped. Please try again."); return
        report(94,"Finishing up...","finishing")
        download=subprocess.run(["kaggle","kernels","output",kernel_ref,"-p",str(output_dir),"-o","-q"],env=env,capture_output=True,text=True,check=False,timeout=60)
        audio_files=list(output_dir.rglob("generated.wav"))
        if download.returncode!=0 or not audio_files:
            update_job(username,job_id,status="failed",error="Generation finished, but the result could not be retrieved."); return
        audio_bytes=audio_files[0].read_bytes()
        if len(audio_bytes)<1000 or not audio_bytes.startswith(b"RIFF"):
            update_job(username,job_id,status="failed",error="Generation produced an invalid audio file."); return
        result=outputs_dir(username)/f"{job_id}.wav"; result.write_bytes(audio_bytes)
        update_job(username,job_id,status="completed",progress=100.0,message="Speech generated successfully.",result_file=str(result))
    except FileNotFoundError:
        update_job(username,job_id,status="failed",error="The generation service is not available right now.")
    except Exception:
        update_job(username,job_id,status="failed",error="Something went wrong during generation. Please try again.")
    finally:
        try: shutil.rmtree(workspace,ignore_errors=True)
        except Exception: pass
        try: shutil.rmtree(output_dir,ignore_errors=True)
        except Exception: pass


def start_generation(username,text,title,voice_path,gen_username,gen_token,char_count):
    jid=create_job(username,"tts",{"text":text,"title":title,"voice_path":str(voice_path),"voice_name":Path(voice_path).stem,"chars":char_count})
    threading.Thread(target=run_generation_job,args=(username,jid,text,str(voice_path),gen_username,gen_token),daemon=True).start()
    return jid

# -------------------- CREDITS --------------------

def charge_once(db, profile, username, jid, chars):
    job=get_job(username,jid)
    if not job or job.get("credits_charged"): return True
    remaining=int(profile.get("remaining_chars",0)); chars=int(chars or 0)
    if chars>remaining:return False
    profile["remaining_chars"]=remaining-chars
    if push_database_updates(db):
        update_job(username,jid,credits_charged=True)
        return True
    return False

# -------------------- UI --------------------
st.markdown("""
<style>
:root{--bg:#050a14;--panel:#0b1324;--panel2:#0e1a2d;--line:rgba(111,210,255,.16);--text:#eef7ff;--muted:#91a4bd;--cyan:#56dcff;--purple:#8b7cff}
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"]{background:radial-gradient(circle at 80% -10%,rgba(92,86,255,.12),transparent 34%),radial-gradient(circle at 10% 10%,rgba(0,210,255,.08),transparent 30%),var(--bg);color:var(--text)}
.block-container{max-width:1180px;padding-top:7.4rem;padding-bottom:2.5rem}
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"], [data-testid="stAppDeployButton"], footer, [data-testid="stSidebar"], #MainMenu{display:none!important;visibility:hidden!important}
.brand{font-weight:900;letter-spacing:.7px;font-size:1.25rem;background:linear-gradient(90deg,#56dcff,#8b7cff,#ff76cf);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.zhead{position:fixed;top:0;left:0;right:0;z-index:9998;background:rgba(5,10,20,.94);backdrop-filter:blur(18px);border-bottom:1px solid var(--line);padding:12px 22px;min-height:66px;display:flex;align-items:center;justify-content:space-between;gap:18px}
.head-brand{display:flex;align-items:center;gap:12px}.metrics{display:flex;gap:24px;align-items:center;justify-content:flex-end;flex-wrap:wrap}.metric-label{font-size:.66rem;text-transform:uppercase;letter-spacing:.09em;color:#7287a3}.metric-value{font-weight:800;color:#f2f7ff;font-size:.92rem}
.zaiko-hamburger{position:fixed;top:17px;left:18px;z-index:10020;width:42px;height:42px;border:1px solid rgba(86,220,255,.20);border-radius:12px;background:rgba(7,14,27,.92);backdrop-filter:blur(12px);display:flex;flex-direction:column;justify-content:center;align-items:center;gap:5px;cursor:pointer;box-shadow:0 10px 30px rgba(0,0,0,.25)}
.zaiko-hamburger span{display:block;width:19px;height:2px;border-radius:4px;background:#bfeeff;transition:.2s}.zaiko-hamburger.open span:nth-child(1){transform:translateY(7px) rotate(45deg)}.zaiko-hamburger.open span:nth-child(2){opacity:0}.zaiko-hamburger.open span:nth-child(3){transform:translateY(-7px) rotate(-45deg)}
.zhead .head-brand{padding-left:52px}.zaiko-menu{position:fixed;top:0;left:-330px;width:300px;height:100vh;z-index:10015;padding:86px 18px 22px;background:rgba(7,14,27,.985);border-right:1px solid var(--line);box-shadow:24px 0 60px rgba(0,0,0,.35);transition:left .22s ease;overflow-y:auto}.zaiko-menu.open{left:0}.zmenu-brand{font-weight:900;font-size:1.05rem;margin:0 8px 18px;background:linear-gradient(90deg,#56dcff,#8b7cff,#ff76cf);-webkit-background-clip:text;-webkit-text-fill-color:transparent}.znav-link{display:flex;align-items:center;gap:12px;text-decoration:none!important;color:#b7c7da!important;padding:12px 13px;border-radius:12px;margin:5px 0;font-weight:700}.znav-link:hover,.znav-link.active{background:rgba(86,220,255,.10);color:#eafaff!important;border:1px solid rgba(86,220,255,.12)}.znav-link span{width:22px;text-align:center}.zmenu-sep{height:1px;background:rgba(255,255,255,.08);margin:18px 4px}.logout-link{color:#ffb4c0!important}
.card,.hero{background:linear-gradient(145deg,rgba(14,26,46,.94),rgba(8,18,33,.91));border:1px solid rgba(126,211,255,.12);border-radius:20px;padding:24px;margin-bottom:18px;box-shadow:0 18px 45px rgba(0,0,0,.25)}.card:hover{border-color:rgba(86,220,255,.22)}.hero h1{margin:0 0 6px}.muted,.small{color:var(--muted)}
.footer{text-align:center;margin-top:48px;padding:28px 10px;color:#8193aa;border-top:1px solid rgba(255,255,255,.07)}
.wa{display:inline-block;margin-top:10px;padding:10px 17px;border-radius:12px;border:1px solid rgba(86,220,255,.28);background:rgba(86,220,255,.08);color:#9eeaff!important;text-decoration:none;font-weight:800}
.login-wrap{max-width:520px;margin:7vh auto}.login-brand{text-align:center;font-size:2rem}.typewriter{min-height:86px;text-align:center;font-size:1.35rem;font-weight:900;line-height:1.45;background:linear-gradient(90deg,#56dcff,#8b7cff,#ff76cf);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:22px 0 26px}
.section-title{font-size:1.1rem;font-weight:800;margin:2px 0 14px}.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#5ff2a8;box-shadow:0 0 12px #5ff2a8;margin-right:7px}
.stButton>button{border-radius:12px;border:1px solid rgba(86,220,255,.18);min-height:44px}.stButton>button:disabled{background:#172238!important;color:#596982!important}
textarea[aria-label="Enter Your Text"]{height:260px!important;max-height:260px!important;overflow-y:auto!important}
[data-testid="stMetric"]{background:rgba(14,26,46,.68);border:1px solid rgba(126,211,255,.10);border-radius:16px;padding:14px}
.stat-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:8px 0 20px}.stat-card{background:linear-gradient(145deg,rgba(14,26,46,.96),rgba(8,18,33,.92));border:1px solid rgba(126,211,255,.12);border-radius:16px;padding:16px}.stat-card .label{font-size:.66rem;text-transform:uppercase;letter-spacing:.08em;color:#7287a3}.stat-card .value{font-size:1.18rem;font-weight:900;margin-top:5px}.account-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.account-box{background:rgba(14,26,46,.78);border:1px solid rgba(126,211,255,.10);border-radius:15px;padding:16px}.account-box .label{font-size:.68rem;text-transform:uppercase;color:#7287a3;letter-spacing:.08em}.account-box .value{font-weight:850;font-size:1.03rem;margin-top:5px}.server-progress{margin-top:14px}.zui-history-scroll{max-height:680px;overflow-y:auto;padding-right:6px}.server-log{background:#050a14;border:1px solid rgba(86,220,255,.10);border-radius:12px;padding:12px;color:#9fb3ca;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.78rem}
@media(max-width:760px){.block-container{padding-top:7.5rem}.zhead{padding:10px 12px;align-items:flex-start}.metrics{gap:9px;justify-content:flex-end}.metric-value{font-size:.76rem}.metric-label{font-size:.55rem}.head-brand .brand{font-size:1rem}.hero,.card{padding:18px;border-radius:16px}.login-wrap{margin:4vh auto}.typewriter{font-size:1.05rem}.stat-grid,.account-grid{grid-template-columns:1fr}.zhead .metrics{margin-left:46px}}
</style>
""",unsafe_allow_html=True)

# -------------------- SESSION STATE --------------------
for k,v in {"auth_session":False,"current_user":"","session_id":"","page":"Dashboard","menu_open":False,"show_token":False}.items():
    if k not in st.session_state: st.session_state[k]=v

# Public share route works without exposing credentials.
share_token=st.query_params.get("share")
if share_token:
    shared=get_share(share_token)
    if shared:
        _, job=shared
        st.markdown(f'<div class="login-wrap"><div class="login-brand brand">{BRAND}</div><div class="card"><h2>{html.escape(job.get("title","Shared Audio"))}</h2><p class="small">Voice: {html.escape(job.get("voice_name",""))}</p>',unsafe_allow_html=True)
        audio=Path(job["result_file"])
        st.audio(audio.read_bytes(),format="audio/wav")
        st.download_button("Download Audio",audio.read_bytes(),file_name=f'{safe_filename(job.get("title","audio"))}.wav',mime="audio/wav",use_container_width=True)
        st.markdown('</div></div>',unsafe_allow_html=True)
    else:
        st.error("This shared audio link has expired or is no longer available.")
    st.stop()

user_db=fetch_live_database()

# Explicit logout route: only this action destroys the server-side session.
if st.query_params.get("logout") == "1":
    sid = cookie_session_id()
    if sid:
        remove_session(sid)
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    clear_cookie()
    st.stop()

# -------------------- AUTH RESTORE --------------------
if not st.session_state.auth_session:
    sid=cookie_session_id()
    username=resolve_session(sid) if sid else None
    if username and username in user_db and not user_db[username].get("is_revoked",False):
        st.session_state.auth_session=True; st.session_state.current_user=username; st.session_state.session_id=sid; touch_session(sid)


def login_page():
    # Credentials are never written to query parameters.
    st.markdown(f'''<div class="login-wrap">
      <div class="login-brand brand">{BRAND}</div>
      <div id="typewriter" class="typewriter"></div>
      <div class="card"><h2 style="margin-top:0">Welcome back</h2>''',unsafe_allow_html=True)
    components.html('''<script>
      const lines=["Give Your Words a Voice.","Turn Text Into Natural Speech.","Where Every Word Comes Alive.","Speak. Create. Inspire."];
      let i=0,n=0,del=false; const root=window.parent.document.getElementById('typewriter');
      function tick(){if(!root)return;const s=lines[i];if(!del){n++;root.textContent=s.slice(0,n);if(n===s.length){del=true;setTimeout(tick,1400);return}}else{n--;root.textContent=s.slice(0,n);if(n===0){del=false;i=(i+1)%lines.length}}setTimeout(tick,del?34:62)} tick();
    </script>''',height=0)
    with st.form("login_form"):
        username=st.text_input("Username",key="login_user").upper().strip()
        password=st.text_input("Password",type="password",key="login_pass")
        submitted=st.form_submit_button("Sign In",type="primary",use_container_width=True)
    if submitted:
        target=user_db.get(username)
        if not target or target.get("password")!=password:
            st.error("Invalid username or password.")
        elif target.get("is_revoked"):
            st.error("This account no longer has access. Please contact support.")
        else:
            try: exp=datetime.strptime(target.get("expiry_timestamp",""),"%Y-%m-%d %H:%M:%S")
            except Exception: exp=datetime.now()+timedelta(days=1)
            if exp<datetime.now() and not target.get("is_admin",False): st.error("Your plan has expired. Please contact support to renew.")
            else:
                sid=create_session(username)
                st.session_state.auth_session=True; st.session_state.current_user=username; st.session_state.session_id=sid; st.session_state.page="Dashboard"
                set_cookie(sid, redirect_page="Dashboard")
                st.stop()
    st.markdown('</div>',unsafe_allow_html=True)
    msg=quote(f"Hi {ADMIN_CONTACT_NAME}, I want to request access to {BRAND}.")
    st.markdown(f'''<div class="card" style="text-align:center"><div style="font-weight:800">Need access?</div><div class="small">{ADMIN_CONTACT_NAME}</div><a class="wa" href="https://wa.me/{WHATSAPP_NUMBER_INTL}?text={msg}" target="_blank">💬 Contact on WhatsApp</a></div></div>''',unsafe_allow_html=True)

if not st.session_state.auth_session:
    login_page(); st.stop()

active_username=st.session_state.current_user
if active_username not in user_db or user_db[active_username].get("is_revoked",False):
    remove_session(st.session_state.session_id); st.session_state.auth_session=False; st.session_state.current_user=""; clear_cookie(); st.stop()
profile=user_db[active_username]; is_admin=bool(profile.get("is_admin",False)); valid_pages=ADMIN_PAGES if is_admin else CLIENT_PAGES
requested_page=st.query_params.get("page")
if requested_page in valid_pages: st.session_state.page=requested_page
if st.session_state.page not in valid_pages: st.session_state.page=valid_pages[0]
page=st.session_state.page


def goto(p):
    st.session_state.page=p; st.query_params["page"]=p; st.rerun()


def logout():
    remove_session(st.session_state.get("session_id",""))
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.query_params.clear(); st.query_params["logout"]="1"; st.rerun()


def expiry_dt():
    try:return datetime.strptime(profile.get("expiry_timestamp",""),"%Y-%m-%d %H:%M:%S")
    except Exception:return datetime.now()


def header():
    if page=="History" and not is_admin:
        items=prune_history(active_username); dates=[]
        for x in items:
            try: dates.append(datetime.fromisoformat(x["generated_at"]).date())
            except Exception: pass
        rng=f'{min(dates).strftime("%d %b %Y")} – {max(dates).strftime("%d %b %Y")}' if dates else "No history"
        metrics=f'''<div class="metrics"><div><div class="metric-label">Total Voices Generated</div><div class="metric-value">{len(items):,}</div></div><div><div class="metric-label">Voices Available in History</div><div class="metric-value">{len(items):,}</div></div><div><div class="metric-label">Available History</div><div class="metric-value">{rng}</div></div></div>'''
    else:
        exp=expiry_dt(); left=max(0,int((exp-datetime.now()).total_seconds())); d,left=divmod(left,86400); h,left=divmod(left,3600); m,s=divmod(left,60)
        total=int(profile.get("total_credits_allocated",profile.get("total_limit",0))); rem=int(profile.get("remaining_chars",0))
        metrics=f'''<div class="metrics"><div><div class="metric-label">Total Credits</div><div class="metric-value">{total:,}</div></div><div><div class="metric-label">Remaining Credits</div><div class="metric-value">{rem:,}</div></div><div><div class="metric-label">Plan Expiry</div><div class="metric-value" id="expiry-count">{d} Days {h} Hours {m} Minutes {s} Seconds</div><div class="small">Expires: {exp.strftime("%d %b %Y, %I:%M %p")}</div></div></div>'''
    nav_items=[p for p in valid_pages]
    links="".join([f'<a href="?page={quote(item)}" class="znav-link {"active" if item==page else ""}"><span>{PAGE_ICONS.get(item,"•")}</span>{html.escape(item)}</a>' for item in nav_items])
    menu=f'''<div id="zaiko-menu" class="zaiko-menu"><div class="zmenu-brand">{BRAND}</div>{links}<div class="zmenu-sep"></div><a href="?logout=1" class="znav-link logout-link"><span>↪</span>Logout</a></div><div id="zaiko-menu-backdrop"></div>'''
    st.markdown(f'''<div class="zhead"><div class="head-brand"><span class="brand">{BRAND}</span></div>{metrics}</div>''',unsafe_allow_html=True)
    components.html(f'''<script>
    (function() {{
      const doc=window.parent.document;
      const oldBtn=doc.getElementById('zaiko-hamburger'); if(oldBtn) oldBtn.remove();
      const oldWrap=doc.getElementById('zaiko-drawer-wrap'); if(oldWrap) oldWrap.remove();
      const btn=doc.createElement('button'); btn.id='zaiko-hamburger'; btn.className='zaiko-hamburger'; btn.setAttribute('aria-label','Open menu');
      btn.innerHTML='<span></span><span></span><span></span>'; doc.body.appendChild(btn);
      const wrap=doc.createElement('div'); wrap.id='zaiko-drawer-wrap'; wrap.innerHTML=`{menu}`; doc.body.appendChild(wrap);
      const menuEl=doc.getElementById('zaiko-menu'), backdrop=doc.getElementById('zaiko-menu-backdrop');
      function closeMenu(){{menuEl.classList.remove('open');btn.classList.remove('open');}}
      function toggle(){{menuEl.classList.toggle('open');btn.classList.toggle('open');}}
      btn.onclick=toggle; backdrop.onclick=closeMenu;
      doc.querySelectorAll('#zaiko-menu a').forEach(a=>a.addEventListener('click',closeMenu));
    }})();
    </script>''',height=0)
    if page!="History" and not is_admin:
        iso=expiry_dt().isoformat()
        components.html(f'''<script>const ex=new Date("{iso}");function t(){{let x=Math.max(0,Math.floor((ex-new Date())/1000));let d=Math.floor(x/86400);x%=86400;let h=Math.floor(x/3600);x%=3600;let m=Math.floor(x/60),s=x%60;let e=window.parent.document.getElementById('expiry-count');if(e)e.textContent=`${{d}} Days ${{h}} Hours ${{m}} Minutes ${{s}} Seconds`;}}t();setInterval(t,1000);</script>''',height=0)


def footer():
    msg=quote(f"Hi, I want to know more about {BRAND}.")
    st.markdown(f'''<div class="footer"><div class="brand">{BRAND}</div><div class="small">Built by M Zakriya</div><a class="wa" href="https://wa.me/{WHATSAPP_NUMBER_INTL}?text={msg}" target="_blank" rel="noopener">💬 Contact on WhatsApp</a></div>''',unsafe_allow_html=True)


# -------------------- PAGE RENDERERS --------------------

def page_dashboard():
    header()
    st.markdown(f'''<div class="hero"><h1>Welcome back, {html.escape(active_username.title())}</h1><p class="muted"><span class="status-dot"></span>Your creative workspace is ready.</p></div>''',unsafe_allow_html=True)
    total=int(profile.get("total_credits_allocated",profile.get("total_limit",0))); rem=int(profile.get("remaining_chars",0)); exp=expiry_dt()
    st.markdown(f'''<div class="stat-grid">
      <div class="stat-card"><div class="label">Total Credits</div><div class="value">{total:,}</div></div>
      <div class="stat-card"><div class="label">Remaining Credits</div><div class="value">{rem:,}</div></div>
      <div class="stat-card"><div class="label">Plan Expiry</div><div class="value">{exp.strftime("%d %b %Y")}</div><div class="small">{exp.strftime("%I:%M %p")}</div></div>
    </div>''',unsafe_allow_html=True)
    if st.button("Start Voice Cloning",type="primary",use_container_width=True): goto("Voice Cloning")
    footer()


def page_voice_cloning():
    header(); st.markdown("## Voice Cloning"); st.caption("Save a short reference voice under a name you will recognize.")
    st.markdown('<div class="card">',unsafe_allow_html=True)
    name=st.text_input("Voice Name",placeholder="e.g. Guru Ji",max_chars=80,key="vc_name")
    st.caption("Give your saved voice a simple name or label.")
    up=st.file_uploader("Upload Reference Voice",type=[x.lstrip('.') for x in SUPPORTED_VOICE_EXT],key="vc_upload")
    st.caption("Maximum duration: 12 seconds for better results • Supported: WAV, MP3, M4A, OGG, FLAC")
    if up:
        suffix=Path(up.name).suffix.lower(); dur=uploaded_audio_duration(up)
        if suffix not in SUPPORTED_VOICE_EXT: st.error("Please upload an audio file in a supported format.")
        else:
            detail=f"{up.name} • {up.size/1024:.1f} KB"
            if dur is not None: detail+=f" • {dur:.2f}s"
            st.caption(detail)
            if dur is not None and dur>MAX_VOICE_SECONDS: st.error("Please upload a voice sample of 12 seconds or less.")
    saving=st.session_state.get("vc_saving",False)
    if st.button("Save Voice Clone",type="primary",use_container_width=True,disabled=saving):
        clean=name.strip()
        dur=uploaded_audio_duration(up) if up else None
        if not clean: st.error("Please enter a voice name.")
        elif not up: st.error("Please upload a voice file.")
        elif dur is not None and dur>MAX_VOICE_SECONDS: st.error("Please upload a voice sample of 12 seconds or less.")
        else:
            st.session_state.vc_saving=True; bar=st.progress(0); msg=st.empty(); msg.info("Preparing..."); bar.progress(15); time.sleep(.12); msg.info("Uploading..."); bar.progress(65); time.sleep(.12)
            ext=Path(up.name).suffix.lower(); dest=voice_dir(active_username)/(safe_filename(clean)+ext)
            dest.write_bytes(up.getbuffer()); msg.info("Saving to database..."); bar.progress(82)
            if not save_voice_to_database(active_username,dest):
                dest.unlink(missing_ok=True); st.session_state.vc_saving=False; st.error("Voice could not be saved to the database. Please try again.")
            else:
                msg.info("Voice saved..."); bar.progress(100); st.session_state.vc_saving=False; st.success(f'Voice "{clean}" saved successfully.'); time.sleep(.2); st.rerun()
    st.markdown('</div>',unsafe_allow_html=True)
    st.markdown("### My Voices")
    vs=saved_voices(active_username)
    if not vs:
        st.info("Upload Your First Voice")
    for v in vs:
        st.markdown('<div class="card">',unsafe_allow_html=True); a,b=st.columns([4,1]); a.markdown(f"**{html.escape(v.stem)}**"); b1=b.button("Delete",key="del_"+v.name)
        try: a.audio(v.read_bytes(),format="audio/"+v.suffix.lstrip('.'))
        except Exception: pass
        confirm="confirm_"+v.name
        if b1: st.session_state[confirm]=True
        if st.session_state.get(confirm):
            st.warning(f'Delete "{v.stem}"? This voice sample will be permanently removed.')
            c1,c2=st.columns(2)
            if c1.button("Cancel",key="cancel_"+v.name): st.session_state[confirm]=False; st.rerun()
            if c2.button("Delete",key="confirm_"+v.name):
                if delete_voice_from_database(active_username,v.stem):
                    v.unlink(missing_ok=True); st.session_state[confirm]=False; st.rerun()
                else:
                    st.error("Voice could not be removed from the database. Please try again.")
        st.markdown('</div>',unsafe_allow_html=True)
    footer()


def process_completed_jobs():
    jobs=all_jobs(active_username); completed=[j for j in jobs if j.get("type")=="tts" and j.get("status")=="completed"]
    for job in completed:
        if not job.get("credits_charged"):
            if not charge_once(user_db,profile,active_username,job["job_id"],job.get("chars",0)):
                update_job(active_username,job["job_id"],status="failed",error="Your credits could not be updated. Please contact support."); continue
        if not job.get("history_recorded") and job.get("result_file") and Path(job["result_file"]).exists():
            add_history(active_username,{"job_id":job["job_id"],"title":job.get("title","Untitled"),"voice_name":job.get("voice_name",""),"audio_path":job["result_file"],"generated_at":datetime.now().isoformat()})
            update_job(active_username,job["job_id"],history_recorded=True)


def result_card(job):
    result=Path(job.get("result_file", ""))
    if not result.exists(): return
    st.markdown('<div class="card">',unsafe_allow_html=True); st.success("Speech generated successfully."); st.markdown(f"### {html.escape(job.get('title','Untitled'))}"); st.caption(f"Voice: {html.escape(job.get('voice_name',''))}")
    audio=result.read_bytes(); st.audio(audio,format="audio/wav")
    a,b=st.columns(2); a.download_button("Download",audio,file_name=f'{safe_filename(job.get("title","audio"))}.wav',mime="audio/wav",use_container_width=True,key="download_"+job["job_id"])
    token=create_share(active_username,job["job_id"])
    if token:
        # Build a share link using the current app URL while keeping credentials out of it.
        try: base=st.context.url
        except Exception: base=""
        if base:
            share_url=base.split("?")[0]+"?share="+token
            if b.button("Share",use_container_width=True,key="share_"+job["job_id"]): st.session_state["share_url"]=share_url
        if st.session_state.get("share_url"):
            st.text_input("Shareable link",value=st.session_state["share_url"],key="share_link_display")
            st.caption("Share links expire after 7 days.")
    st.markdown('</div>',unsafe_allow_html=True)


def page_tts():
    header(); st.markdown("## Turn Your Text Into Speech"); st.caption("Prepare the generation connection first, then create your speech without waiting for the server to start.")
    gen_user=str(profile.get("kaggle_username","")).strip(); gen_token=str(profile.get("kaggle_token","")).strip()
    server=get_server_state(active_username); status=server.get("status","disconnected")

    st.markdown('<div class="card">',unsafe_allow_html=True)
    st.markdown("### Generation Connection")
    if status=="connected":
        st.success("● Connected — your generation server is ready.")
        if st.button("Disconnect",use_container_width=True,key="disconnect_server"):
            disconnect_server(active_username,gen_user,gen_token); st.rerun()
    elif status=="starting":
        pct=float(server.get("progress",0)); st.info(server.get("message","Connecting..."))
        st.progress(int(pct))
        st.caption(f"{pct:.0f}%")
        if st.button("Refresh Connection Status",use_container_width=True,key="refresh_server"): st.rerun()
        time.sleep(1.2); st.rerun()
    elif status=="error":
        st.error(server.get("message","The generation server could not be started."))
        if st.button("Connect to Server",type="primary",use_container_width=True,key="connect_server_error"):
            start_server_connection(active_username,gen_user,gen_token); st.rerun()
    else:
        st.caption("Start the server once. The connection status and setup progress will appear here.")
        if st.button("Connect to Server",type="primary",use_container_width=True,key="connect_server"):
            start_server_connection(active_username,gen_user,gen_token); st.rerun()
    if status in {"starting","connected"}:
        st.markdown(f'<div class="server-log">{html.escape(server.get("message","Waiting..."))}</div>',unsafe_allow_html=True)
    st.markdown('</div>',unsafe_allow_html=True)

    vs=saved_voices(active_username)
    if not vs:
        st.warning("No saved voice found. Add one in Voice Cloning first.")
        if st.button("Open Voice Cloning",use_container_width=True): goto("Voice Cloning")
        footer(); return

    active=active_job(active_username,"tts")
    names=[v.stem for v in vs]; active_voice=active.get("voice_name") if active else st.session_state.get("tts_voice",names[0]); idx=names.index(active_voice) if active_voice in names else 0
    st.markdown('<div class="card">',unsafe_allow_html=True)
    voice=st.selectbox("Select Your Voice",names,index=idx,disabled=bool(active)); selected=next(v for v in vs if v.stem==voice)
    text_default=active.get("text","") if active else st.session_state.get("tts_text","")
    text=st.text_area("Enter Your Text",value=text_default,height=260,placeholder="Type your text here...",disabled=bool(active),key="tts_text_area")
    if not active: st.session_state.tts_text=text; st.session_state.tts_voice=voice
    count=len(text); rem=int(profile.get("remaining_chars",0)); a,b=st.columns(2); a.metric("Characters in this script",f"{count:,}"); b.metric("Remaining after generation",f"{max(rem-count,0):,}")
    title_default=active.get("title","") if active else st.session_state.get("tts_title","")
    title=st.text_input("Audio Title",value=title_default,placeholder="Technology",disabled=bool(active),key="tts_title_input")
    if not active: st.session_state.tts_title=title
    if count>rem and not active: st.error("Not enough credits for this script.")
    connected=(status=="connected")
    clicked=st.button("Generate Speech",type="primary",use_container_width=True,disabled=bool(active) or not connected or count==0 or count>rem)
    if clicked and not active:
        snapshot_title=title.strip() or "Untitled"
        jid=start_generation(active_username,text,snapshot_title,selected,gen_user,gen_token,count)
        update_job(active_username,jid,status="queued",progress=0.0,message="Generation request accepted. Preparing batches...")
        st.rerun()
    st.markdown('</div>',unsafe_allow_html=True)

    if active:
        pct=float(active.get("progress",0)); msg=active.get("message","Preparing your speech...")
        st.markdown('<div class="card">',unsafe_allow_html=True)
        st.markdown("### Generation Progress")
        st.progress(int(max(0,min(100,pct))))
        st.markdown(f"**{pct:.1f}%** — {html.escape(msg)}")
        chars=int(active.get("chars",0)); batches=max(1,(chars+399)//400)
        done=max(0,min(batches,int(round((pct/100)*batches))))
        st.caption(f"Batches: {done}/{batches} generated")
        if active.get("status")=="failed": st.error(active.get("error") or "Generation failed. Please try again.")
        elif active.get("status")!="completed": st.caption("You can safely refresh. Your job and progress are saved on the server.")
        st.markdown('</div>',unsafe_allow_html=True)
        if active.get("status") not in {"failed","completed","cancelled"}:
            time.sleep(1.2); st.rerun()

    process_completed_jobs()
    jobs=[j for j in all_jobs(active_username) if j.get("type")=="tts" and j.get("status")=="completed" and j.get("result_file")]
    if jobs:
        latest=max(jobs,key=lambda x:x.get("updated",x.get("created","")))
        result_card(latest)
    footer()


def page_history():
    header(); items=prune_history(active_username); items.sort(key=lambda x:x.get("generated_at",""),reverse=True)
    choice=st.radio("Filter",["Yesterday","2 Days","7 Days"],index=2,horizontal=True); days={"Yesterday":1,"2 Days":2,"7 Days":7}[choice]; cutoff=datetime.now()-timedelta(days=days); filtered=[]
    for x in items:
        try:
            if datetime.fromisoformat(x["generated_at"])>=cutoff: filtered.append(x)
        except Exception: pass
    st.markdown('<div class="zui-history-scroll">',unsafe_allow_html=True)
    if not filtered: st.info("No history in this range.")
    else:
        current=None; now=datetime.now()
        for item in filtered:
            ts=datetime.fromisoformat(item["generated_at"]); heading="Today" if ts.date()==now.date() else ("Yesterday" if ts.date()==(now-timedelta(days=1)).date() else ts.strftime("%d %b %Y"))
            if heading!=current: st.markdown(f"#### {heading}"); current=heading
            st.markdown('<div class="card">',unsafe_allow_html=True); st.markdown(f"**{html.escape(item.get('title','Untitled'))}**"); st.caption(f"Voice: {html.escape(item.get('voice_name',''))} • Generated: {ts.strftime('%d %b %Y • %I:%M %p')}")
            audio=Path(item.get("audio_path",""))
            if audio.exists():
                data=audio.read_bytes(); st.audio(data,format="audio/wav"); a,b=st.columns(2); a.download_button("Download",data,file_name=f'{safe_filename(item.get("title","audio"))}.wav',mime="audio/wav",key="hist_dl_"+item.get("job_id",uuid.uuid4().hex));
                token=create_share(active_username,item.get("job_id")) if item.get("job_id") else None
                if token:
                    try: base=st.context.url; url=base.split("?")[0]+"?share="+token
                    except Exception: url=""
                    if url and b.button("Share",key="hist_share_"+item.get("job_id",uuid.uuid4().hex)): st.session_state["history_share_url"]=url
                    if st.session_state.get("history_share_url"): st.text_input("Shareable link",value=st.session_state["history_share_url"],key="hist_share_url")
            else: st.caption("This audio is no longer available.")
            st.markdown('</div>',unsafe_allow_html=True)
    st.markdown('</div>',unsafe_allow_html=True); footer()


def page_settings():
    header(); st.markdown("## Settings")
    st.markdown('<div class="card">',unsafe_allow_html=True)
    st.markdown("### Generation Connection"); st.caption("Save the account used for your generation connection. Credentials are masked by default.")
    saved_u=str(profile.get("kaggle_username","") or ""); saved_t=str(profile.get("kaggle_token","") or "")
    show=st.checkbox("Show token",value=st.session_state.get("show_token",False)); st.session_state.show_token=show
    with st.form("connection_form"):
        u=st.text_input("Username",value=saved_u)
        t=st.text_input("API Token",value=saved_t,type="default" if show else "password")
        a,b,c=st.columns(3)
        save=a.form_submit_button("Save Credentials",use_container_width=True)
        verify=b.form_submit_button("Verify Credentials",use_container_width=True)
        remove=c.form_submit_button("Remove Credentials",use_container_width=True)
    if save:
        if not u.strip() or not t.strip():
            st.error("✕ Unable to save credentials. Please check your details and try again.")
        else:
            old_u,old_t=profile.get("kaggle_username",""),profile.get("kaggle_token","")
            profile["kaggle_username"]=u.strip(); profile["kaggle_token"]=t.strip()
            if push_database_updates(user_db): st.success("✓ Credentials saved successfully.")
            else:
                profile["kaggle_username"]=old_u; profile["kaggle_token"]=old_t
                st.error("✕ Unable to save credentials. Please check your details and try again.")
    if verify:
        with st.spinner("Verifying..."):
            uok,tok,err=verify_generation_credentials(u.strip(),t.strip())
        if err: st.warning(err)
        else:
            st.write("✓ Username — Valid" if uok else "✕ Username — Invalid")
            st.write("✓ API Token — Valid" if tok else "✕ API Token — Invalid")
            if uok and tok: st.success("Credentials verified successfully.")
    if remove: st.session_state.confirm_remove=True
    if st.session_state.get("confirm_remove"):
        st.warning("Remove your saved credentials? You will need to enter them again before using voice generation.")
        a,b=st.columns(2)
        if a.button("Cancel",key="cancel_remove"):
            st.session_state.confirm_remove=False; st.rerun()
        if b.button("Remove",key="remove_confirm"):
            old_u,old_t=profile.get("kaggle_username",""),profile.get("kaggle_token","")
            profile["kaggle_username"]=profile["kaggle_token"]=""
            ok=push_database_updates(user_db)
            if ok:
                st.session_state.confirm_remove=False; st.success("✓ Credentials removed successfully.")
                st.rerun()
            else:
                profile["kaggle_username"]=old_u; profile["kaggle_token"]=old_t
                st.error("Unable to remove credentials right now. Nothing was changed.")
    st.markdown('</div>',unsafe_allow_html=True)
    footer()


def page_account():
    header(); st.markdown("## Account")
    total=int(profile.get("total_credits_allocated",profile.get("total_limit",0))); rem=int(profile.get("remaining_chars",0)); exp=expiry_dt()
    st.markdown(f'''<div class="card"><h3 style="margin-top:0">Account Overview</h3><div class="account-grid">
      <div class="account-box"><div class="label">Username</div><div class="value">{html.escape(active_username)}</div></div>
      <div class="account-box"><div class="label">Account Status</div><div class="value">Active</div></div>
      <div class="account-box"><div class="label">Total Credits</div><div class="value">{total:,}</div></div>
      <div class="account-box"><div class="label">Remaining Credits</div><div class="value">{rem:,}</div></div>
      <div class="account-box"><div class="label">Plan Expiry</div><div class="value">{exp.strftime("%d %b %Y")}</div></div>
      <div class="account-box"><div class="label">Expiry Time</div><div class="value">{exp.strftime("%I:%M %p")}</div></div>
    </div></div>''',unsafe_allow_html=True)

    st.markdown('<div class="card">',unsafe_allow_html=True); st.markdown("### Change Password")
    with st.form("change_password"):
        old=st.text_input("Current Password",type="password")
        new=st.text_input("New Password",type="password")
        confirm=st.text_input("Confirm New Password",type="password")
        change=st.form_submit_button("Change Password",use_container_width=True)
    if change:
        if profile.get("password")!=old: st.error("Current password is incorrect.")
        elif not new: st.error("Please enter a new password.")
        elif new!=confirm: st.error("New passwords do not match.")
        else:
            old_pw=profile.get("password"); profile["password"]=new
            if push_database_updates(user_db): st.success("Password changed successfully.")
            else: profile["password"]=old_pw; st.error("Unable to change password right now.")
    st.markdown('</div>',unsafe_allow_html=True)

    st.markdown('<div class="card">',unsafe_allow_html=True); st.markdown("### Connected Devices")
    current=st.session_state.get("session_id"); sessions=sessions_for_user(active_username)
    if not sessions: st.caption("No active devices found.")
    for s in sessions:
        is_current=s["sid"]==current; ua=html.escape(s.get("user_agent","Unknown browser")); ip=html.escape(s.get("ip","Unavailable")); last=html.escape(s.get("last_seen","—"))
        st.markdown(f'''<div class="account-box" style="margin:10px 0"><strong>{"This device" if is_current else "Other device"}</strong><div class="small">Browser / OS: {ua}</div><div class="small">IP: {ip}</div><div class="small">Last active: {last}</div></div>''',unsafe_allow_html=True)
        if not is_current:
            if st.button("Remove Access",key="remove_device_"+s["sid"]): st.session_state["confirm_device"]=s["sid"]
            if st.session_state.get("confirm_device")==s["sid"]:
                st.warning("Remove access from this device? It will be logged out.")
                a,b=st.columns(2)
                if a.button("Cancel",key="cancel_dev_"+s["sid"]): st.session_state.pop("confirm_device",None); st.rerun()
                if b.button("Remove Access",key="confirm_dev_"+s["sid"]): remove_session(s["sid"]); st.session_state.pop("confirm_device",None); st.rerun()
    st.markdown('</div>',unsafe_allow_html=True); footer()


# -------------------- ADMIN --------------------

def admin_dashboard():
    header(); st.markdown(f"## Welcome, {html.escape(active_username.title())}"); st.caption("Administrator workspace")
    regular=[x for x in user_db.values() if not x.get("is_admin",False)]; active=sum(1 for x in regular if not x.get("is_revoked",False)); a,b=st.columns(2); a.metric("Total Clients",len(regular)); b.metric("Active Clients",active); footer()


def admin_registry():
    header(); st.markdown("## Active Users Registry")
    for n,x in [(n,x) for n,x in user_db.items() if not x.get("is_admin",False)]:
        with st.expander(f'{n} — {"Revoked" if x.get("is_revoked") else "Active"}'):
            current=int(x.get("remaining_chars",0)); add=st.number_input("Add Credits",min_value=0,value=0,key="add_"+n); new_exp_days=st.number_input("Extend Plan Days",min_value=0,value=0,key="days_"+n)
            st.caption(f'Current remaining: {current:,} • Cumulative allocated: {int(x.get("total_credits_allocated",x.get("total_limit",0))):,}')
            a,b=st.columns(2)
            if a.button("Revoke / Grant",key="toggle_"+n,use_container_width=True): x["is_revoked"]=not x.get("is_revoked",False); push_database_updates(user_db); st.rerun()
            if b.button("Save Changes",key="save_"+n,use_container_width=True):
                if add: x["remaining_chars"]=current+int(add); x["total_credits_allocated"]=int(x.get("total_credits_allocated",x.get("total_limit",0)))+int(add); x["total_limit"]=x["total_credits_allocated"]
                if new_exp_days:
                    e=expiry_dt() if n==active_username else datetime.strptime(x["expiry_timestamp"],"%Y-%m-%d %H:%M:%S"); x["expiry_timestamp"]=(max(e,datetime.now())+timedelta(days=int(new_exp_days))).strftime("%Y-%m-%d %H:%M:%S")
                if push_database_updates(user_db): st.rerun()
    footer()


def admin_deploy():
    header(); st.markdown("## Deploy New Client")
    with st.form("deploy_form"):
        u=st.text_input("New Client Username").upper().strip(); pw=st.text_input("Set Login Password",type="password"); days=st.number_input("Plan Duration (Days)",min_value=1,value=30); chars=st.number_input("Character Allocation",min_value=1000,value=1000000); go=st.form_submit_button("Deploy User",type="primary",use_container_width=True)
    if go:
        if not u or not pw: st.error("Username and password are required.")
        elif u in user_db: st.error("That username already exists.")
        else:
            amount=int(chars); user_db[u]={"password":pw,"expiry_timestamp":(datetime.now()+timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S"),"total_limit":amount,"total_credits_allocated":amount,"remaining_chars":amount,"is_revoked":False,"is_admin":False,"kaggle_username":"","kaggle_token":""}
            if push_database_updates(user_db): st.success(f"User {u} created successfully."); st.rerun()
            else: st.error("We couldn't create the account right now.")
    footer()


def admin_settings():
    header(); st.markdown("## Settings"); st.info("Core storage configuration is managed securely outside this interface."); footer()

# -------------------- ROUTER --------------------
if is_admin:
    routes={"Dashboard":admin_dashboard,"Active Users Registry":admin_registry,"Deploy New Client":admin_deploy,"Settings":admin_settings}
else:
    routes={"Dashboard":page_dashboard,"Voice Cloning":page_voice_cloning,"Text To Speech":page_tts,"History":page_history,"Settings":page_settings,"Account":page_account}

routes.get(page,routes[valid_pages[0]])()
