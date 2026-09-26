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
from datetime import datetime, timedelta
from pathlib import Path
import requests

# ============================================================
# Z UI STUDIO
# ============================================================

st.set_page_config(
    page_title="Z UI Studio",
    page_icon="🎧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------- INTERNAL CONFIG (never shown to normal users) --------------------

REPO_OWNER = "mfazil78761-glitch"
REPO_NAME = "F5-TTS-AK"
DB_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/users_db.json"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/users_db.json"
GITHUB_PAT_TOKEN = str(st.secrets.get("GITHUB_PAT_TOKEN", "")).strip()

DATA_ROOT = Path("cloud_vault")
DATA_ROOT.mkdir(parents=True, exist_ok=True)

SESSIONS_FILE = DATA_ROOT / "_sessions.json"
_FILE_LOCKS = {}
_FILE_LOCKS_GUARD = threading.Lock()

WHATSAPP_NUMBER_INTL = "923097647772"
WHATSAPP_DISPLAY = "0309 764 7772"
ADMIN_CONTACT_NAME = "Muhammad Zukriya"

VALID_PAGES_CLIENT = [
    "Dashboard", "Voice Cloning", "Text To Speech", "History", "Settings", "Account",
]
VALID_PAGES_ADMIN = [
    "Dashboard", "Active Users Registry", "Deploy New Client", "Settings",
]

PAGE_ICONS = {
    "Dashboard": "🏠", "Voice Cloning": "🎙️", "Text To Speech": "🔊",
    "History": "🕘", "Settings": "⚙️", "Account": "👤",
    "Active Users Registry": "👑", "Deploy New Client": "➕",
}

HISTORY_RETENTION_DAYS = 7

# -------------------- FILE-BASED PERSISTENCE HELPERS --------------------

def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _FILE_LOCKS_GUARD:
        if key not in _FILE_LOCKS:
            _FILE_LOCKS[key] = threading.Lock()
        return _FILE_LOCKS[key]


def load_json(path: Path, default):
    lock = _lock_for(path)
    with lock:
        if not path.exists():
            return json.loads(json.dumps(default))
        try:
            return json.loads(path.read_text(encoding="utf-8") or "null") or json.loads(json.dumps(default))
        except Exception:
            return json.loads(json.dumps(default))


def save_json(path: Path, data):
    lock = _lock_for(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def user_dir(username: str) -> Path:
    p = DATA_ROOT / username
    p.mkdir(parents=True, exist_ok=True)
    return p


def voice_dir(username: str) -> Path:
    p = user_dir(username) / "voices"
    p.mkdir(parents=True, exist_ok=True)
    return p


def jobs_file(username: str) -> Path:
    return user_dir(username) / "jobs.json"


def active_job_file(username: str) -> Path:
    return user_dir(username) / "active_job.json"


def history_file(username: str) -> Path:
    return user_dir(username) / "history.json"


def outputs_dir(username: str) -> Path:
    p = user_dir(username) / "outputs"
    p.mkdir(parents=True, exist_ok=True)
    return p


# -------------------- GITHUB "DATABASE" (of user accounts) --------------------

def fallback_database():
    return {
        "AKKHAN": {
            "password": "AKKHAN90",
            "expiry_timestamp": "2030-12-31 23:59:59",
            "total_limit": 99999999,
            "remaining_chars": 99999999,
            "is_revoked": False,
            "is_admin": True,
            "kaggle_username": "",
            "kaggle_token": "",
        }
    }


def fetch_live_database():
    try:
        res = requests.get(DB_URL, timeout=15)
        if res.status_code == 200:
            users = res.json().get("users", {})
            if users:
                return users
    except Exception:
        pass
    return fallback_database()


def push_database_updates(updated_db_dict):
    if not GITHUB_PAT_TOKEN:
        st.error("Account storage is not configured. Please contact support.")
        return False

    headers = {
        "Authorization": f"Bearer {GITHUB_PAT_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Z-UI-Studio",
    }
    try:
        get_res = requests.get(GITHUB_API_URL, headers=headers, timeout=15)
        if get_res.status_code != 200:
            st.error("We couldn't update your account right now. Please try again shortly.")
            return False
        sha = get_res.json().get("sha")
        content = json.dumps({"users": updated_db_dict}, indent=2, ensure_ascii=False).encode("utf-8")
        payload = {
            "message": "Update accounts",
            "content": base64.b64encode(content).decode("ascii"),
            "sha": sha,
        }
        put_res = requests.put(GITHUB_API_URL, headers=headers, json=payload, timeout=15)
        if put_res.status_code in (200, 201):
            return True
        st.error("We couldn't update your account right now. Please try again shortly.")
        return False
    except Exception:
        st.error("We couldn't update your account right now. Please try again shortly.")
        return False


# -------------------- SESSIONS (cookie-based, no credentials in URL) --------------------

def _load_sessions():
    return load_json(SESSIONS_FILE, {})


def _save_sessions(sessions):
    save_json(SESSIONS_FILE, sessions)


def create_session(username: str) -> str:
    sessions = _load_sessions()
    sid = uuid.uuid4().hex
    now = datetime.now().isoformat()
    sessions[sid] = {
        "username": username,
        "created": now,
        "last_seen": now,
    }
    _save_sessions(sessions)
    return sid


def touch_session(sid: str):
    sessions = _load_sessions()
    if sid in sessions:
        sessions[sid]["last_seen"] = datetime.now().isoformat()
        _save_sessions(sessions)


def resolve_session(sid: str):
    if not sid:
        return None
    sessions = _load_sessions()
    entry = sessions.get(sid)
    if not entry:
        return None
    return entry.get("username")


def remove_session(sid: str):
    sessions = _load_sessions()
    if sid in sessions:
        del sessions[sid]
        _save_sessions(sessions)


def list_sessions_for_user(username: str):
    sessions = _load_sessions()
    return [
        {"sid": sid, **info}
        for sid, info in sessions.items()
        if info.get("username") == username
    ]


def set_session_cookie(sid: str, max_age_days: int = 30):
    max_age = max_age_days * 24 * 60 * 60
    components.html(
        f"""
        <script>
        document.cookie = "zui_session={sid}; path=/; max-age={max_age}; samesite=Lax";
        setTimeout(function() {{ window.location.reload(); }}, 150);
        </script>
        """,
        height=0,
    )


def clear_session_cookie():
    components.html(
        """
        <script>
        document.cookie = "zui_session=; path=/; max-age=0";
        setTimeout(function() { window.location.reload(); }, 150);
        </script>
        """,
        height=0,
    )


def get_cookie_session_id():
    try:
        cookies = st.context.cookies
        return cookies.get("zui_session")
    except Exception:
        return None


# -------------------- GENERATION SETTINGS (labelled "Generation Connection" to clients) --------------------

def save_generation_credentials(user_db, account_profile, gen_username, gen_token):
    account_profile["kaggle_username"] = gen_username.strip()
    account_profile["kaggle_token"] = gen_token.strip()
    return push_database_updates(user_db)


def remove_generation_credentials(user_db, account_profile):
    account_profile["kaggle_username"] = ""
    account_profile["kaggle_token"] = ""
    return push_database_updates(user_db)


def verify_generation_credentials(gen_username, gen_token):
    """Best-effort verification against the underlying provider."""
    username_ok, token_ok = False, False
    if not gen_username:
        return False, False, "Enter a username."
    if not gen_token:
        return username_ok, False, "Enter an API token."
    env = os.environ.copy()
    env["KAGGLE_USERNAME"] = gen_username
    env["KAGGLE_API_TOKEN"] = gen_token
    env["KAGGLE_KEY"] = gen_token
    try:
        result = subprocess.run(
            ["kaggle", "kernels", "list", "--mine"],
            env=env, capture_output=True, text=True, timeout=30, check=False,
        )
        combined = ((result.stdout or "") + (result.stderr or "")).lower()
        if result.returncode == 0:
            username_ok = True
            token_ok = True
        elif "401" in combined or "unauthorized" in combined or "invalid" in combined:
            username_ok = False
            token_ok = False
        else:
            # Ambiguous network/tooling error - don't claim invalid.
            return False, False, "Could not verify right now. Please try again."
    except FileNotFoundError:
        return False, False, "Verification tool is unavailable on this server."
    except Exception:
        return False, False, "Could not verify right now. Please try again."
    return username_ok, token_ok, None


# -------------------- JOB STORE (persistent, survives refresh) --------------------

def _job_lock(username):
    return _lock_for(jobs_file(username))


def create_job(username, job_type, payload):
    lock = _job_lock(username)
    with lock:
        jobs = load_json(jobs_file(username), {})
        job_id = uuid.uuid4().hex
        now = datetime.now().isoformat()
        jobs[job_id] = {
            "job_id": job_id,
            "type": job_type,
            "status": "queued",
            "progress": 0.0,
            "message": "Queued...",
            "created": now,
            "updated": now,
            "credits_charged": False,
            "error": None,
            "result_file": None,
            **payload,
        }
        save_json(jobs_file(username), jobs)
        save_json(active_job_file(username), {"job_id": job_id, "type": job_type})
        return job_id


def update_job(username, job_id, **fields):
    lock = _job_lock(username)
    with lock:
        jobs = load_json(jobs_file(username), {})
        if job_id not in jobs:
            return
        jobs[job_id].update(fields)
        jobs[job_id]["updated"] = datetime.now().isoformat()
        save_json(jobs_file(username), jobs)


def get_job(username, job_id):
    jobs = load_json(jobs_file(username), {})
    return jobs.get(job_id)


def get_active_job(username, job_type=None):
    active = load_json(active_job_file(username), {})
    job_id = active.get("job_id")
    if not job_id:
        return None
    job = get_job(username, job_id)
    if not job:
        return None
    if job_type and job.get("type") != job_type:
        return None
    if job.get("status") in ("completed", "failed", "cancelled"):
        return None
    return job


def clear_active_job(username, job_id):
    active = load_json(active_job_file(username), {})
    if active.get("job_id") == job_id:
        save_json(active_job_file(username), {})


# -------------------- HISTORY STORE --------------------

def add_history_entry(username, entry):
    lock = _lock_for(history_file(username))
    with lock:
        items = load_json(history_file(username), [])
        items.append(entry)
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
                out_path = Path(item.get("audio_path", ""))
                if out_path.exists():
                    try:
                        out_path.unlink()
                    except Exception:
                        pass
        save_json(history_file(username), kept)
        return kept


def get_history(username):
    return prune_history(username)


# -------------------- VOICE HELPERS --------------------

SUPPORTED_VOICE_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


def get_saved_voices(username):
    d = voice_dir(username)
    return sorted(
        [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_VOICE_EXT],
        key=lambda p: p.name.lower(),
    )


def audio_duration_seconds(path: Path):
    try:
        import wave
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / float(rate) if rate else None
    except Exception:
        pass
    return None


def character_count(text: str) -> int:
    return len(text)


def safe_filename(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in (" ", "_", "-") else "_" for c in name).strip()
    return cleaned or "audio"


# -------------------- GENERATION ENGINE (backend detail, hidden from client UI) --------------------

def _run_generation_job(username, job_id, text, voice_path_str, gen_username, gen_token):
    def report(percent, message, status="generating"):
        update_job(username, job_id, progress=max(0.0, min(100.0, float(percent))),
                   message=message, status=status)

    try:
        report(2, "Preparing your request...", status="connecting")

        voice_file = Path(voice_path_str)
        if not voice_file.exists() or voice_file.stat().st_size == 0:
            update_job(username, job_id, status="failed", error="The selected voice is missing. Please re-upload it.")
            return
        if not gen_username or not gen_token:
            update_job(username, job_id, status="failed", error="Generation is not configured for this account yet.")
            return

        voice_b64 = base64.b64encode(voice_file.read_bytes()).decode("ascii")
        text_json = json.dumps(text, ensure_ascii=False)
        raw_slug = f"zui-{username.lower()}-{job_id[:10]}"
        kernel_slug = "".join(c if c.isalnum() or c == "-" else "-" for c in raw_slug).strip("-")[:80]

        report(10, "Connecting to server...", status="connecting")
        workspace = Path(tempfile.mkdtemp(prefix="zui_job_"))
        notebook_path = workspace / "active_worker.ipynb"
        metadata_path = workspace / "kernel-metadata.json"
        output_dir = Path(tempfile.mkdtemp(prefix="zui_job_output_"))

        notebook_source = """import base64
import json
import subprocess
import sys
from pathlib import Path

OUTPUT = Path('/kaggle/working')
STATUS = OUTPUT / 'status.json'
AUDIO = OUTPUT / 'generated.wav'
VOICE = OUTPUT / 'reference_voice.wav'

TEXT = __TEXT_JSON__
VOICE_B64 = __VOICE_B64__


def write_status(status, message='', percent=None):
    payload = {'status': status, 'message': message}
    if percent is not None:
        payload['percent'] = float(percent)
    STATUS.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


class LiveChunkProgress:
    def tqdm(self, iterable, *args, **kwargs):
        items = list(iterable)
        total = len(items)
        if total == 0:
            return
        for index, item in enumerate(items, 1):
            yield item
            percent = (index / total) * 100.0
            write_status('generating', f'chunk {index}/{total}', percent=percent)
            print(f'PROGRESS {index}/{total} {percent:.1f}%', flush=True)


try:
    write_status('starting', 'Preparing engine', percent=0)
    VOICE.write_bytes(base64.b64decode(VOICE_B64))
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'f5-tts'])
    write_status('generating', 'Generation started', percent=0)
    print('GENERATION STARTED 0.0%', flush=True)

    from f5_tts.api import F5TTS

    tts = F5TTS(model='F5TTS_v1_Base', device='cuda')
    progress = LiveChunkProgress()
    tts.infer(
        ref_file=str(VOICE), ref_text='', gen_text=TEXT, progress=progress,
        file_wave=str(AUDIO), remove_silence=False,
    )

    if not AUDIO.exists() or AUDIO.stat().st_size < 1000:
        raise RuntimeError('Generation finished without producing a valid audio file.')

    write_status('success', 'Audio generated successfully', percent=100.0)
    print('GENERATION COMPLETE 100.0%', flush=True)
except Exception as exc:
    write_status('error', repr(exc))
    print('GENERATION ERROR:', repr(exc), flush=True)
"""
        notebook_source = notebook_source.replace("__TEXT_JSON__", text_json).replace("__VOICE_B64__", repr(voice_b64))
        notebook = {
            "cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                       "source": notebook_source.splitlines(True)}],
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 5,
        }
        notebook_path.write_text(json.dumps(notebook, indent=2, ensure_ascii=False), encoding="utf-8")

        metadata = {
            "id": f"{gen_username}/{kernel_slug}", "title": kernel_slug, "code_file": "active_worker.ipynb",
            "language": "python", "kernel_type": "notebook", "is_private": True, "enable_gpu": True,
            "enable_internet": True, "machine_shape": "NvidiaTeslaT4",
            "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": [],
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        env = os.environ.copy()
        env["KAGGLE_USERNAME"] = gen_username
        env["KAGGLE_API_TOKEN"] = gen_token
        env["KAGGLE_KEY"] = gen_token

        report(20, "Connected to server", status="connected")
        report(25, "Generating your speech...", status="generating")

        pushed = subprocess.run(["kaggle", "kernels", "push", "-p", str(workspace)], env=env,
                                 capture_output=True, text=True, check=False)
        if pushed.returncode != 0:
            update_job(username, job_id, status="failed", error="We couldn't start your generation. Please try again.")
            return

        kernel_ref = f"{gen_username}/{kernel_slug}"
        last_progress = 25
        started = False

        def probe_output():
            probe_dir = Path(tempfile.mkdtemp(prefix="zui_probe_"))
            try:
                probe = subprocess.run(
                    ["kaggle", "kernels", "output", kernel_ref, "-p", str(probe_dir), "-o", "-q"],
                    env=env, capture_output=True, text=True, check=False,
                )
                status_candidates = list(probe_dir.rglob("status.json"))
                audio_candidates = list(probe_dir.rglob("generated.wav"))
                status_payload = None
                if status_candidates:
                    try:
                        status_payload = json.loads(status_candidates[0].read_text(encoding="utf-8"))
                    except Exception:
                        status_payload = None
                return status_payload, bool(audio_candidates)
            finally:
                shutil.rmtree(probe_dir, ignore_errors=True)

        final_state = None
        restart_count = 0

        while True:
            log_process = subprocess.Popen(
                ["kaggle", "kernels", "logs", kernel_ref, "--follow"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            try:
                while True:
                    ready, _, _ = select.select([log_process.stdout], [], [], 2.0)
                    if ready:
                        line = log_process.stdout.readline()
                        if not line:
                            break
                        upper = line.upper()
                        if any(m in upper for m in ("KERNEL FAILED", "TRACEBACK", "RUNTIMEERROR", "EXCEPTION", "CANCELLED")):
                            final_state = "error"
                            break
                        match = re.search(r"PROGRESS\s+(\d+)\s*/\s*(\d+)\s+(\d+(?:\.\d+)?)%", line)
                        if match:
                            started = True
                            pct = float(match.group(3))
                            last_progress = max(25, pct)
                            report(last_progress, "Generating your speech...")
                        elif started:
                            report(last_progress, "Generating your speech...")
                        else:
                            report(20, "Connecting to server...")
                    elif log_process.poll() is not None:
                        break
            finally:
                if log_process.stdout:
                    log_process.stdout.close()
                if log_process.poll() is None:
                    log_process.terminate()
                    log_process.wait()

            if final_state == "error":
                break

            status_payload, audio_ready = probe_output()
            if status_payload:
                if status_payload.get("status") == "error":
                    final_state = "error"
                    break
                if status_payload.get("status") == "success" and audio_ready:
                    final_state = "complete"
                    break
            if audio_ready:
                final_state = "complete"
                break

            restart_count += 1
            if restart_count > 200:
                final_state = "error"
                break
            report(last_progress, "Generating your speech...")
            time.sleep(2)

        if final_state == "error":
            update_job(username, job_id, status="failed", error="Generation could not be completed. Please try again.")
            return

        report(92, "Finishing up...")
        download = subprocess.run(["kaggle", "kernels", "output", kernel_ref, "-p", str(output_dir), "-o", "-q"],
                                   env=env, capture_output=True, text=True, check=False)
        if download.returncode != 0:
            update_job(username, job_id, status="failed", error="Generation finished, but the result could not be retrieved.")
            return

        audio_files = list(output_dir.rglob("generated.wav"))
        if not audio_files:
            update_job(username, job_id, status="failed", error="Generation finished, but no audio was produced.")
            return
        audio_bytes = audio_files[0].read_bytes()
        if len(audio_bytes) < 1000 or not audio_bytes.startswith(b"RIFF"):
            update_job(username, job_id, status="failed", error="Generation produced an invalid audio file.")
            return

        job = get_job(username, job_id) or {}
        title = job.get("title") or "Untitled"
        result_path = outputs_dir(username) / f"{job_id}.wav"
        result_path.write_bytes(audio_bytes)

        update_job(username, job_id, status="completed", progress=100.0,
                   message="Speech generated successfully.", result_file=str(result_path))

    except FileNotFoundError:
        update_job(username, job_id, status="failed", error="The generation service is not available right now.")
    except Exception:
        update_job(username, job_id, status="failed", error="Something went wrong during generation. Please try again.")


def start_generation_job(username, text, title, voice_path, gen_username, gen_token, char_count):
    job_id = create_job(username, "tts", {
        "text": text, "title": title, "voice_path": str(voice_path),
        "voice_name": Path(voice_path).stem, "chars": char_count,
    })
    thread = threading.Thread(
        target=_run_generation_job,
        args=(username, job_id, text, str(voice_path), gen_username, gen_token),
        daemon=True,
    )
    thread.start()
    return job_id


# -------------------- CREDIT HANDLING (idempotent) --------------------

def charge_credits_once(user_db, account_profile, username, job_id, chars):
    job = get_job(username, job_id)
    if not job or job.get("credits_charged"):
        return True
    current = int(account_profile.get("remaining_chars", 0))
    if chars > current:
        return False
    account_profile["remaining_chars"] = current - chars
    if push_database_updates(user_db):
        update_job(username, job_id, credits_charged=True)
        return True
    return False


# -------------------- STYLE --------------------

st.markdown(
    """
<style>
#MainMenu, header[data-testid="stHeader"] {visibility: visible;}
.main {background: #060912;}
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1100px;}

.zui-header {
    position: sticky; top: 0; z-index: 999;
    background: linear-gradient(135deg, rgba(10,14,26,0.96), rgba(15,25,45,0.96));
    border: 1px solid rgba(80,180,255,0.18);
    border-radius: 18px;
    padding: 16px 22px;
    margin-bottom: 20px;
    box-shadow: 0 8px 30px rgba(0,0,0,.35), 0 0 40px rgba(120,80,255,.06);
    backdrop-filter: blur(6px);
}
.zui-brand {
    font-size: 1.35rem; font-weight: 800; letter-spacing: .5px;
    background: linear-gradient(90deg, #5ee7ff, #8a7bff);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.zui-metric-row {display: flex; gap: 26px; flex-wrap: wrap; margin-top: 6px;}
.zui-metric-label {font-size: .72rem; color: #7f8bab; text-transform: uppercase; letter-spacing: .06em;}
.zui-metric-value {font-size: 1.05rem; color: #e8ecff; font-weight: 700;}

.card {
    padding: 22px; border-radius: 18px;
    background: rgba(20,26,45,.72);
    border: 1px solid rgba(255,255,255,.06);
    margin-bottom: 18px;
    box-shadow: 0 6px 22px rgba(0,0,0,.25);
}
.card:hover {border-color: rgba(94,231,255,.25);}

.zui-nav-active {
    color: #5ee7ff !important; font-weight: 700 !important;
    background: rgba(94,231,255,.08);
    border-radius: 10px;
}

.zui-footer {
    margin-top: 40px; padding: 22px; text-align: center;
    color: #8892b0; border-top: 1px solid rgba(255,255,255,.06);
}
.zui-footer a {color: #5ee7ff; text-decoration: none; font-weight: 600;}

.zui-history-scroll {
    max-height: 560px; overflow-y: auto; padding-right: 8px;
}

.small-muted {opacity: .7; font-size: .85rem;}

textarea[aria-label="Enter Your Text"] {
    height: 260px !important;
    max-height: 260px !important;
    overflow-y: auto !important;
}

.stButton>button:disabled {
    background: #1b2338 !important; color: #55607f !important;
    border: 1px solid rgba(255,255,255,.05) !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# -------------------- SESSION STATE DEFAULTS --------------------

defaults = {
    "auth_checked": False,
    "auth_session": False,
    "current_user": "",
    "menu_open": False,
}
for key, default in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default

user_db = fetch_live_database()

# -------------------- RESTORE SESSION FROM COOKIE --------------------

if not st.session_state.auth_session:
    sid = get_cookie_session_id()
    if sid:
        username = resolve_session(sid)
        if username and username in user_db and not user_db[username].get("is_revoked", False):
            st.session_state.auth_session = True
            st.session_state.current_user = username
            st.session_state.session_id = sid
            touch_session(sid)

# -------------------- PAGE RESTORE (identifier only, never credentials) --------------------

def restore_page(valid_pages):
    requested = st.query_params.get("page")
    if requested in valid_pages:
        return requested
    return valid_pages[0]


def set_page_param(page_name):
    st.query_params["page"] = page_name


# ============================================================
# LOGIN
# ============================================================

def render_login():
    st.query_params.clear()

    st.markdown(
        """
        <div class="zui-header" style="text-align:center;">
            <div class="zui-brand" style="font-size:2rem;">Z UI Studio</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    components.html(
        """
        <div id="typewriter" style="text-align:center;font-family:'Segoe UI',sans-serif;
             font-weight:700;font-size:1.4rem;min-height:2.2rem;margin-bottom:18px;
             background:linear-gradient(90deg,#5ee7ff,#8a7bff,#ff7bd0);
             -webkit-background-clip:text;-webkit-text-fill-color:transparent;"></div>
        <script>
        const lines = [
            "Give Your Words a Voice.",
            "Turn Text Into Natural Speech.",
            "Where Every Word Comes Alive.",
            "Speak. Create. Inspire."
        ];
        let li = 0, ci = 0, deleting = false;
        const el = document.getElementById("typewriter");
        function tick() {
            const current = lines[li];
            if (!deleting) {
                ci++;
                el.textContent = current.slice(0, ci);
                if (ci === current.length) { deleting = true; setTimeout(tick, 1400); return; }
            } else {
                ci--;
                el.textContent = current.slice(0, ci);
                if (ci === 0) { deleting = false; li = (li + 1) % lines.length; }
            }
            setTimeout(tick, deleting ? 35 : 65);
        }
        tick();
        </script>
        """,
        height=70,
    )

    col_a, col_b, col_c = st.columns([1, 1.2, 1])
    with col_b:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("#### Welcome back")
        with st.form("login_form"):
            username_input = st.text_input("Username").upper().strip()
            password_input = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

            if submitted:
                if username_input not in user_db:
                    st.error("Invalid username or password.")
                else:
                    target = user_db[username_input]
                    if target.get("is_revoked", False):
                        st.error("This account no longer has access. Please contact support.")
                    elif target.get("password") != password_input:
                        st.error("Invalid username or password.")
                    else:
                        try:
                            exp_time = datetime.strptime(target["expiry_timestamp"], "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            exp_time = datetime.now() + timedelta(days=1)
                        if exp_time < datetime.now() and not target.get("is_admin", False):
                            st.error("Your plan has expired. Please contact support to renew.")
                        else:
                            sid = create_session(username_input)
                            st.session_state.auth_session = True
                            st.session_state.current_user = username_input
                            st.session_state.session_id = sid
                            set_session_cookie(sid)
                            st.stop()
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown(
            f"""
            <div class="card" style="text-align:center;">
                <div style="font-weight:700;margin-bottom:6px;">Need access?</div>
                <div class="small-muted">{ADMIN_CONTACT_NAME} · {WHATSAPP_DISPLAY}</div>
                <a href="https://wa.me/{WHATSAPP_NUMBER_INTL}?text={requests.utils.quote(
                    f'Hi {ADMIN_CONTACT_NAME}, I want to request access to Z UI Studio.'
                )}" target="_blank">
                    <button style="margin-top:10px;padding:10px 18px;border-radius:10px;
                        border:1px solid rgba(94,231,255,.35);background:rgba(94,231,255,.08);
                        color:#5ee7ff;font-weight:700;cursor:pointer;">
                        💬 Contact on WhatsApp
                    </button>
                </a>
            </div>
            """,
            unsafe_allow_html=True,
        )


if not st.session_state.auth_session:
    render_login()
    st.stop()


# ============================================================
# ACTIVE PROFILE
# ============================================================

active_username = st.session_state.current_user

if active_username not in user_db:
    remove_session(st.session_state.get("session_id", ""))
    st.session_state.auth_session = False
    clear_session_cookie()
    st.stop()

account_profile = user_db[active_username]
is_admin = account_profile.get("is_admin", False)

if account_profile.get("is_revoked", False):
    remove_session(st.session_state.get("session_id", ""))
    st.session_state.auth_session = False
    clear_session_cookie()
    st.error("Access revoked. Please contact support.")
    st.stop()

valid_pages = VALID_PAGES_ADMIN if is_admin else VALID_PAGES_CLIENT
page = restore_page(valid_pages)


def do_logout():
    remove_session(st.session_state.get("session_id", ""))
    st.session_state.auth_session = False
    st.session_state.current_user = ""
    clear_session_cookie()


# -------------------- NAVIGATION (sidebar doubles as hamburger drawer on mobile) --------------------

with st.sidebar:
    st.markdown('<div class="zui-brand" style="font-size:1.3rem;">☰ Z UI Studio</div>', unsafe_allow_html=True)
    st.caption(active_username.title())
    st.divider()

    for item in valid_pages:
        icon = PAGE_ICONS.get(item, "•")
        active = (item == page)
        label = f"**{icon} {item}**" if active else f"{icon} {item}"
        if st.button(label, key=f"nav_{item}", use_container_width=True):
            set_page_param(item)
            st.rerun()

    st.divider()
    if st.button("🚪 Logout", key="nav_logout", use_container_width=True):
        do_logout()
        st.rerun()


def render_footer():
    msg = requests.utils.quote("Hi, I want to know more about Z UI Studio.")
    st.markdown(
        f"""
        <div class="zui-footer">
            <div class="zui-brand" style="font-size:1.1rem;">Z UI Studio</div>
            <div class="small-muted">Built by Anil Zacharia</div>
            <div style="margin-top:8px;">
                <a href="https://wa.me/{WHATSAPP_NUMBER_INTL}?text={msg}" target="_blank">
                    WhatsApp: {WHATSAPP_DISPLAY}
                </a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_header(show_credits=True):
    remaining = int(account_profile.get("remaining_chars", 0))
    total = int(account_profile.get("total_limit", 0))
    expiry_raw = account_profile.get("expiry_timestamp", "")

    metrics_html = f'<div class="zui-metric-row">'
    if show_credits:
        metrics_html += f"""
            <div><div class="zui-metric-label">Total Credits</div><div class="zui-metric-value">{total:,}</div></div>
            <div><div class="zui-metric-label">Remaining</div><div class="zui-metric-value">{remaining:,}</div></div>
        """
    metrics_html += "</div>"

    st.markdown(
        f"""
        <div class="zui-header">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;">
                <div>
                    <div class="zui-brand">Z UI Studio</div>
                    {metrics_html}
                </div>
                <div id="zui-countdown-{expiry_raw.replace(' ', '').replace(':','')}" style="text-align:right;">
                    <div class="zui-metric-label">Plan Expiry</div>
                    <div class="zui-metric-value" id="zui-countdown-value">–</div>
                    <div class="small-muted" id="zui-expiry-date">–</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not is_admin and expiry_raw:
        components.html(
            f"""
            <script>
            const expiry = new Date("{expiry_raw.replace(' ', 'T')}");
            function fmt(n) {{ return n.toString(); }}
            function tick() {{
                const now = new Date();
                let diff = Math.max(0, (expiry - now) / 1000);
                const d = Math.floor(diff / 86400);
                const h = Math.floor((diff % 86400) / 3600);
                const m = Math.floor((diff % 3600) / 60);
                const s = Math.floor(diff % 60);
                const text = d + "d " + h + "h " + m + "m " + s + "s";
                const parentDoc = window.parent.document;
                const valueEl = parentDoc.getElementById("zui-countdown-value");
                const dateEl = parentDoc.getElementById("zui-expiry-date");
                if (valueEl) valueEl.textContent = text;
                if (dateEl) {{
                    const opts = {{ day: '2-digit', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' }};
                    dateEl.textContent = "Expires: " + expiry.toLocaleString('en-GB', opts);
                }}
            }}
            tick();
            setInterval(tick, 1000);
            </script>
            """,
            height=0,
        )


# ============================================================
# CLIENT PAGES
# ============================================================

def page_dashboard():
    render_header()
    st.markdown(
        f"""
        <div class="card">
            <h2 style="margin-top:0;">Welcome back, {active_username.title()} 👋</h2>
            <p class="small-muted">Your creative workspace is ready.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    voices = get_saved_voices(active_username)
    remaining = int(account_profile.get("remaining_chars", 0))
    total = int(account_profile.get("total_limit", 0))

    col1, col2, col3 = st.columns(3)
    col1.metric("Remaining Credits", f"{remaining:,}")
    col2.metric("Total Credits", f"{total:,}")
    col3.metric("Saved Voices", len(voices))

    if st.button("🚀 Start Voice Cloning", type="primary", use_container_width=True):
        set_page_param("Voice Cloning")
        st.rerun()

    render_footer()


def page_voice_cloning():
    render_header()
    st.markdown("## Voice Cloning")
    st.caption("Upload a short reference sample and save it under a name you'll recognize.")

    st.markdown('<div class="card">', unsafe_allow_html=True)
    voice_name = st.text_input("Voice Name", placeholder="e.g. Guru Ji", max_chars=80, key="voice_name_input")
    uploaded_voice = st.file_uploader(
        "Upload Reference Voice",
        type=["wav", "mp3", "m4a", "ogg", "flac"],
        key="voice_upload_input",
    )
    st.caption("Maximum duration: 12 seconds for better results.")

    if uploaded_voice is not None:
        st.caption(f"Selected: {uploaded_voice.name} · {uploaded_voice.size / 1024:.1f} KB")

    save_clicked = st.button("💾 Save Voice Clone", type="primary", use_container_width=True,
                              disabled=st.session_state.get("voice_saving", False))

    if save_clicked:
        clean_name = voice_name.strip()
        if not clean_name:
            st.error("Please enter a voice name.")
        elif uploaded_voice is None:
            st.error("Please upload a voice file.")
        else:
            st.session_state.voice_saving = True
            progress = st.progress(0)
            status = st.empty()
            status.info("Preparing...")
            progress.progress(30)
            time.sleep(0.2)

            safe_name = safe_filename(clean_name)
            extension = Path(uploaded_voice.name).suffix.lower()
            destination = voice_dir(active_username) / f"{safe_name}{extension}"

            status.info("Uploading...")
            progress.progress(70)
            destination.write_bytes(uploaded_voice.getbuffer())

            status.info("Saving...")
            progress.progress(100)
            st.session_state.voice_saving = False
            status.success("Voice saved successfully.")
            st.success(f'Voice "{clean_name}" saved successfully.')
            time.sleep(0.4)
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("### My Voices")
    voices = get_saved_voices(active_username)

    if not voices:
        st.info("You don't have any saved voices yet.")
    else:
        for voice in voices:
            with st.container():
                st.markdown('<div class="card">', unsafe_allow_html=True)
                c1, c2, c3 = st.columns([3, 3, 1])
                c1.markdown(f"**{voice.stem}**")
                with c2:
                    st.audio(str(voice))
                with c3:
                    confirm_key = f"confirm_delete_{voice.name}"
                    if st.session_state.get(confirm_key):
                        st.warning(f'Delete "{voice.stem}"? This cannot be undone.')
                        cc1, cc2 = st.columns(2)
                        if cc1.button("Cancel", key=f"cancel_{voice.name}"):
                            st.session_state[confirm_key] = False
                            st.rerun()
                        if cc2.button("Delete", key=f"delete_{voice.name}"):
                            voice.unlink(missing_ok=True)
                            st.session_state[confirm_key] = False
                            st.rerun()
                    else:
                        if st.button("🗑️ Delete", key=f"ask_delete_{voice.name}"):
                            st.session_state[confirm_key] = True
                            st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

    render_footer()


def page_text_to_speech():
    render_header()
    st.markdown("## Turn Your Text Into Speech")
    st.caption("Transform your text into natural, expressive speech using your selected voice.")

    voices = get_saved_voices(active_username)
    if not voices:
        st.warning("No saved voice found. Add one in Voice Cloning first.")
        if st.button("🎙️ Open Voice Cloning"):
            set_page_param("Voice Cloning")
            st.rerun()
        render_footer()
        return

    active_job = get_active_job(active_username, job_type="tts")

    voice_names = [v.stem for v in voices]
    default_index = 0
    if active_job and active_job.get("voice_name") in voice_names:
        default_index = voice_names.index(active_job["voice_name"])

    st.markdown('<div class="card">', unsafe_allow_html=True)

    selected_voice = st.selectbox("Select Your Voice", voice_names, index=default_index,
                                   disabled=bool(active_job))
    selected_path = next(p for p in voices if p.stem == selected_voice)

    default_text = active_job.get("text", "") if active_job else st.session_state.get("tts_text_draft", "")
    text_input = st.text_area(
        "Enter Your Text", value=default_text, height=260,
        placeholder="Type your text here...", disabled=bool(active_job), key="tts_text_area",
    )
    if not active_job:
        st.session_state.tts_text_draft = text_input

    current_count = character_count(text_input)
    remaining = int(account_profile.get("remaining_chars", 0))

    c1, c2 = st.columns(2)
    c1.metric("Characters in this script", f"{current_count:,}")
    c2.metric("Remaining after generation", f"{max(remaining - current_count, 0):,}")

    if current_count > remaining and not active_job:
        st.error("Not enough credits for this script.")

    default_title = active_job.get("title", "") if active_job else st.session_state.get("tts_title_draft", "")
    audio_title = st.text_input("Audio Title", value=default_title, placeholder="Technology",
                                 disabled=bool(active_job), key="tts_title_input")
    if not active_job:
        st.session_state.tts_title_draft = audio_title

    generate_disabled = bool(active_job) or current_count == 0 or current_count > remaining
    generate_clicked = st.button("⚡ Generate Speech", type="primary", use_container_width=True,
                                  disabled=generate_disabled)

    if generate_clicked and not active_job:
        gen_username = str(account_profile.get("kaggle_username", "")).strip()
        gen_token = str(account_profile.get("kaggle_token", "")).strip()
        if not gen_username or not gen_token:
            st.error("Please connect your account in Settings before generating.")
        else:
            title_snapshot = audio_title.strip() or "Untitled"
            start_generation_job(
                active_username, text_input, title_snapshot, selected_path,
                gen_username, gen_token, current_count,
            )
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

    # ---- live job status / polling ----
    active_job = get_active_job(active_username, job_type="tts")
    if active_job:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        pct = float(active_job.get("progress", 0))
        st.progress(int(max(0, min(100, pct))))
        st.markdown(f"**{pct:.1f}%** — {active_job.get('message', '')}")
        st.caption("You can safely refresh this page — generation will continue.")
        st.markdown("</div>", unsafe_allow_html=True)

        if active_job.get("status") == "failed":
            st.error(active_job.get("error") or "Generation failed. Please try again.")
            clear_active_job(active_username, active_job["job_id"])
            st.session_state.pop("tts_text_draft", None)
            st.session_state.pop("tts_title_draft", None)
            if st.button("Try Again"):
                st.rerun()
        else:
            time.sleep(1.2)
            st.rerun()

    # ---- most recent completed result (if just finished) ----
    last_job_id = st.session_state.get("last_shown_job")
    jobs = load_json(jobs_file(active_username), {})
    completed_jobs = [j for j in jobs.values() if j.get("status") == "completed"]
    completed_jobs.sort(key=lambda j: j.get("updated", ""), reverse=True)

    if completed_jobs:
        latest = completed_jobs[0]
        if latest["job_id"] != last_job_id:
            # charge credits exactly once, record history
            if not latest.get("credits_charged"):
                charge_credits_once(user_db, account_profile, active_username, latest["job_id"], latest.get("chars", 0))
            if not latest.get("history_recorded"):
                result_file = latest.get("result_file")
                if result_file and Path(result_file).exists():
                    add_history_entry(active_username, {
                        "title": latest.get("title", "Untitled"),
                        "voice_name": latest.get("voice_name", ""),
                        "audio_path": result_file,
                        "generated_at": datetime.now().isoformat(),
                    })
                update_job(active_username, latest["job_id"], history_recorded=True)
            clear_active_job(active_username, latest["job_id"])
            st.session_state.last_shown_job = latest["job_id"]
            st.session_state.pop("tts_text_draft", None)
            st.session_state.pop("tts_title_draft", None)

        result_file = latest.get("result_file")
        if result_file and Path(result_file).exists() and latest["job_id"] == last_job_id:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.success("Speech generated successfully.")
            st.markdown(f"**{latest.get('title', 'Untitled')}**")
            st.caption(f"Voice: {latest.get('voice_name', '')}")
            audio_bytes = Path(result_file).read_bytes()
            st.audio(audio_bytes, format="audio/wav")
            fname = f"{safe_filename(latest.get('title', 'audio'))}.wav"
            st.download_button("⬇️ Download", data=audio_bytes, file_name=fname, mime="audio/wav")
            st.markdown("</div>", unsafe_allow_html=True)

    render_footer()


def page_history():
    render_header(show_credits=False)
    items = get_history(active_username)
    items.sort(key=lambda x: x["generated_at"], reverse=True)

    oldest = items[-1]["generated_at"][:10] if items else datetime.now().strftime("%Y-%m-%d")
    newest = items[0]["generated_at"][:10] if items else datetime.now().strftime("%Y-%m-%d")

    st.markdown(
        f"""
        <div class="zui-header">
            <div class="zui-metric-row">
                <div><div class="zui-metric-label">Total Voices Generated</div>
                     <div class="zui-metric-value">{len(items)}</div></div>
                <div><div class="zui-metric-label">Available History</div>
                     <div class="zui-metric-value">{oldest} – {newest}</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    filter_choice = st.radio("Filter", ["Yesterday", "2 Days", "7 Days"], index=2, horizontal=True)
    now = datetime.now()
    if filter_choice == "Yesterday":
        cutoff = now - timedelta(days=1)
    elif filter_choice == "2 Days":
        cutoff = now - timedelta(days=2)
    else:
        cutoff = now - timedelta(days=7)

    filtered = [i for i in items if datetime.fromisoformat(i["generated_at"]) >= cutoff]

    st.markdown('<div class="zui-history-scroll">', unsafe_allow_html=True)
    if not filtered:
        st.info("No history in this range.")
    else:
        current_heading = None
        for item in filtered:
            ts = datetime.fromisoformat(item["generated_at"])
            if ts.date() == now.date():
                heading = "Today"
            elif ts.date() == (now - timedelta(days=1)).date():
                heading = "Yesterday"
            else:
                heading = ts.strftime("%d %b %Y")

            if heading != current_heading:
                st.markdown(f"#### {heading}")
                current_heading = heading

            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown(f"**{item['title']}**")
            st.caption(f"Voice: {item['voice_name']} · Generated: {ts.strftime('%d %b %Y • %I:%M %p')}")
            audio_path = Path(item["audio_path"])
            if audio_path.exists():
                audio_bytes = audio_path.read_bytes()
                st.audio(audio_bytes, format="audio/wav")
                fname = f"{safe_filename(item['title'])}.wav"
                st.download_button("⬇️ Download", data=audio_bytes, file_name=fname,
                                    key=f"dl_{item['generated_at']}")
            else:
                st.caption("This audio is no longer available.")
            st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    render_footer()


def page_settings():
    render_header()
    st.markdown("## Settings")
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### Generation Connection")
    st.caption("Connect the account used to power your generations.")

    saved_username = account_profile.get("kaggle_username", "")
    saved_token = account_profile.get("kaggle_token", "")

    show_token = st.checkbox("Show token", value=False, key="show_gen_token")
    with st.form("gen_connection_form"):
        gen_username = st.text_input("Username", value=saved_username)
        gen_token = st.text_input("API Token", value=saved_token,
                                   type="default" if show_token else "password")
        col1, col2, col3 = st.columns(3)
        save_clicked = col1.form_submit_button("Save Credentials", use_container_width=True)
        verify_clicked = col2.form_submit_button("Verify Credentials", use_container_width=True)
        remove_clicked = col3.form_submit_button("Remove Credentials", use_container_width=True)

    if save_clicked:
        if not gen_username.strip() or not gen_token.strip():
            st.error("✕ Unable to save credentials. Please check your details and try again.")
        elif save_generation_credentials(user_db, account_profile, gen_username, gen_token):
            st.success("✓ Credentials saved successfully.")
            st.rerun()

    if verify_clicked:
        with st.spinner("Verifying..."):
            username_ok, token_ok, err = verify_generation_credentials(gen_username.strip(), gen_token.strip())
        if err:
            st.warning(err)
        else:
            st.write("✓ Username — Valid" if username_ok else "✕ Username — Invalid")
            st.write("✓ API Token — Valid" if token_ok else "✕ API Token — Invalid")
            if username_ok and token_ok:
                st.success("Credentials verified successfully.")

    if remove_clicked:
        st.session_state.confirm_remove_gen = True

    if st.session_state.get("confirm_remove_gen"):
        st.warning("Remove your saved credentials? You will need to enter them again before using voice generation.")
        cc1, cc2 = st.columns(2)
        if cc1.button("Cancel", key="cancel_remove_gen"):
            st.session_state.confirm_remove_gen = False
            st.rerun()
        if cc2.button("Remove", key="confirm_remove_gen_btn"):
            if remove_generation_credentials(user_db, account_profile):
                st.session_state.confirm_remove_gen = False
                st.success("✓ Credentials removed successfully.")
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
    render_footer()


def page_account():
    render_header()
    st.markdown("## Account")

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### Account Overview")
    c1, c2 = st.columns(2)
    c1.metric("Username", active_username)
    c1.metric("Total Credits", f"{int(account_profile.get('total_limit', 0)):,}")
    c2.metric("Account Status", "Revoked" if account_profile.get("is_revoked") else "Active")
    c2.metric("Remaining Credits", f"{int(account_profile.get('remaining_chars', 0)):,}")
    st.caption(f"Expires: {account_profile.get('expiry_timestamp', '—')}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### Change Password")
    with st.form("change_password_form"):
        current_pw = st.text_input("Current Password", type="password")
        new_pw = st.text_input("New Password", type="password")
        change_clicked = st.form_submit_button("Change Password", use_container_width=True)

    if change_clicked:
        if account_profile.get("password") != current_pw:
            st.error("Current password is incorrect.")
        elif not new_pw:
            st.error("Please enter a new password.")
        else:
            account_profile["password"] = new_pw
            if push_database_updates(user_db):
                st.success("Password changed successfully.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("#### Where Your Account Is Connected")
    sessions = list_sessions_for_user(active_username)
    current_sid = st.session_state.get("session_id")
    if not sessions:
        st.info("No active sessions found.")
    for s in sessions:
        is_current = s["sid"] == current_sid
        st.markdown(
            f"""
            <div class="card" style="margin-bottom:10px;">
                <div><strong>{"This device" if is_current else "Other device"}</strong></div>
                <div class="small-muted">Signed in: {s.get('created', '—')}</div>
                <div class="small-muted">Last active: {s.get('last_seen', '—')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if not is_current:
            confirm_key = f"confirm_remove_{s['sid']}"
            if st.session_state.get(confirm_key):
                st.warning("Remove access from this device? This device will be logged out and its current session will no longer be valid.")
                cc1, cc2 = st.columns(2)
                if cc1.button("Cancel", key=f"cancel_dev_{s['sid']}"):
                    st.session_state[confirm_key] = False
                    st.rerun()
                if cc2.button("Remove Access", key=f"remove_dev_{s['sid']}"):
                    remove_session(s["sid"])
                    st.session_state[confirm_key] = False
                    st.rerun()
            else:
                if st.button("Remove Access", key=f"ask_remove_dev_{s['sid']}"):
                    st.session_state[confirm_key] = True
                    st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    render_footer()


# ============================================================
# ADMIN PAGES
# ============================================================

def page_admin_dashboard():
    render_header(show_credits=False)
    st.markdown(f"## Welcome, {active_username.title()} 👑")
    st.info("Master Administrator")
    regular_users = [u for u in user_db.values() if not u.get("is_admin", False)]
    active_count = sum(1 for u in regular_users if not u.get("is_revoked", False))
    col1, col2 = st.columns(2)
    col1.metric("Total Clients", len(regular_users))
    col2.metric("Active Clients", active_count)
    render_footer()


def page_admin_registry():
    render_header(show_credits=False)
    st.markdown("## Active Users Registry")

    regular_users = [(name, info) for name, info in user_db.items() if not info.get("is_admin", False)]
    if not regular_users:
        st.info("No regular users are registered.")

    for u_name, u_info in regular_users:
        with st.expander(f"{u_name} — {'🔴 Revoked' if u_info.get('is_revoked') else '🟢 Active'}"):
            new_limit = st.number_input("Remaining Characters", min_value=0,
                                         value=int(u_info.get("remaining_chars", 0)), key=f"limit_{u_name}")
            add_days = st.number_input("Extend Plan Days", min_value=0, value=0, key=f"days_{u_name}")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔴 Revoke / 🟢 Grant", key=f"toggle_{u_name}", use_container_width=True):
                    u_info["is_revoked"] = not u_info.get("is_revoked", False)
                    if push_database_updates(user_db):
                        st.rerun()
            with col2:
                if st.button("💾 Save Changes", key=f"save_{u_name}", use_container_width=True):
                    u_info["remaining_chars"] = int(new_limit)
                    if add_days > 0:
                        try:
                            curr_exp = datetime.strptime(u_info["expiry_timestamp"], "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            curr_exp = datetime.now()
                        if curr_exp < datetime.now():
                            curr_exp = datetime.now()
                        u_info["expiry_timestamp"] = (curr_exp + timedelta(days=int(add_days))).strftime("%Y-%m-%d %H:%M:%S")
                    if push_database_updates(user_db):
                        st.rerun()
    render_footer()


def page_admin_deploy():
    render_header(show_credits=False)
    st.markdown("## Deploy New Client")

    with st.form("new_user_registration_form"):
        reg_user = st.text_input("New Client Username").upper().strip()
        reg_pass = st.text_input("Set Login Password", type="password")
        reg_days = st.number_input("Plan Duration (Days)", min_value=1, value=30)
        reg_chars = st.number_input("Character Allocation", min_value=1000, value=1000000)
        create_user = st.form_submit_button("🚀 Deploy User", use_container_width=True)

        if create_user:
            if not reg_user or not reg_pass:
                st.error("Username and password are required.")
            elif reg_user in user_db:
                st.error("That username already exists.")
            else:
                expiry = (datetime.now() + timedelta(days=int(reg_days))).strftime("%Y-%m-%d %H:%M:%S")
                user_db[reg_user] = {
                    "password": reg_pass, "expiry_timestamp": expiry,
                    "total_limit": int(reg_chars), "remaining_chars": int(reg_chars),
                    "is_revoked": False, "is_admin": False,
                    "kaggle_username": "", "kaggle_token": "",
                }
                if push_database_updates(user_db):
                    st.success(f"User {reg_user} created successfully.")
                    st.rerun()
    render_footer()


def page_admin_settings():
    render_header(show_credits=False)
    st.markdown("## Administrator Settings")
    st.info("Core storage configuration is managed outside this interface.")
    render_footer()


# ============================================================
# ROUTER
# ============================================================

if is_admin:
    router = {
        "Dashboard": page_admin_dashboard,
        "Active Users Registry": page_admin_registry,
        "Deploy New Client": page_admin_deploy,
        "Settings": page_admin_settings,
    }
else:
    router = {
        "Dashboard": page_dashboard,
        "Voice Cloning": page_voice_cloning,
        "Text To Speech": page_text_to_speech,
        "History": page_history,
        "Settings": page_settings,
        "Account": page_account,
    }

router.get(page, router[valid_pages[0]])()
