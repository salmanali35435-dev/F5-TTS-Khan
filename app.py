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


def set_cookie(sid, max_age_days=30):
    max_age = max_age_days * 86400
    components.html(
        f'''<script>
        document.cookie = "zaiko_session={sid}; path=/; max-age={max_age}; samesite=Lax";
        setTimeout(function(){{window.parent.location.reload();}},150);
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
            update_job(username, job_id, status="failed", error="Generation is not connected yet. Please open Settings.")
            return

        report(3, "Preparing your request...", "connecting")
        voice_b64 = base64.b64encode(voice_file.read_bytes()).decode("ascii")
        text_json = json.dumps(text, ensure_ascii=False)
        kernel_slug = re.sub(r"[^a-z0-9-]", "-", f"zaiko-{username.lower()}-{job_id[:10]}").strip("-")[:80]
        workspace = Path(tempfile.mkdtemp(prefix="zaiko_job_"))
        output_dir = Path(tempfile.mkdtemp(prefix="zaiko_output_"))
        notebook_path = workspace / "active_worker.ipynb"
        metadata_path = workspace / "kernel-metadata.json"

        source = """import base64, json, subprocess, sys
from pathlib import Path
OUTPUT=Path('/kaggle/working'); STATUS=OUTPUT/'status.json'; AUDIO=OUTPUT/'generated.wav'; VOICE=OUTPUT/'reference_voice.wav'
TEXT=__TEXT_JSON__; VOICE_B64=__VOICE_B64__
def write_status(status,message='',percent=None):
    d={'status':status,'message':message}
    if percent is not None:d['percent']=float(percent)
    STATUS.write_text(json.dumps(d,ensure_ascii=False),encoding='utf-8')
class LiveProgress:
    def tqdm(self, iterable,*args,**kwargs):
        items=list(iterable); total=len(items)
        if total==0:return
        for i,item in enumerate(items,1):
            yield item; pct=(i/total)*100.0; write_status('generating',f'chunk {i}/{total}',pct); print(f'PROGRESS {i}/{total} {pct:.1f}%',flush=True)
try:
    write_status('starting','Preparing engine',0); VOICE.write_bytes(base64.b64decode(VOICE_B64)); subprocess.check_call([sys.executable,'-m','pip','install','-q','f5-tts']); write_status('generating','Generation started',0)
    from f5_tts.api import F5TTS
    tts=F5TTS(model='F5TTS_v1_Base',device='cuda'); progress=LiveProgress(); tts.infer(ref_file=str(VOICE),ref_text='',gen_text=TEXT,progress=progress,file_wave=str(AUDIO),remove_silence=False)
    if not AUDIO.exists() or AUDIO.stat().st_size<1000: raise RuntimeError('No valid audio was produced.')
    write_status('success','Audio generated successfully',100); print('GENERATION COMPLETE 100.0%',flush=True)
except Exception as exc:
    write_status('error',repr(exc)); print('GENERATION ERROR:',repr(exc),flush=True)
"""
        source = source.replace("__TEXT_JSON__", text_json).replace("__VOICE_B64__", repr(voice_b64))
        notebook = {"cells":[{"cell_type":"code","execution_count":None,"metadata":{},"outputs":[],"source":source.splitlines(True)}],"metadata":{"kernelspec":{"display_name":"Python 3","language":"python","name":"python3"},"language_info":{"name":"python"}},"nbformat":4,"nbformat_minor":5}
        notebook_path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")
        metadata = {"id":f"{gen_username}/{kernel_slug}","title":kernel_slug,"code_file":"active_worker.ipynb","language":"python","kernel_type":"notebook","is_private":True,"enable_gpu":True,"enable_internet":True,"machine_shape":"NvidiaTeslaT4","dataset_sources":[],"competition_sources":[],"kernel_sources":[],"model_sources":[]}
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        env=os.environ.copy(); env["KAGGLE_USERNAME"]=gen_username; env["KAGGLE_API_TOKEN"]=gen_token; env["KAGGLE_KEY"]=gen_token
        report(12,"Connecting to server...","connecting")
        pushed=subprocess.run(["kaggle","kernels","push","-p",str(workspace)],env=env,capture_output=True,text=True,check=False)
        if pushed.returncode!=0:
            update_job(username,job_id,status="failed",error="We couldn't start your generation. Please try again."); return
        report(18,"Connected to server","connected")
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
.block-container{max-width:1180px;padding-top:6.5rem;padding-bottom:2.5rem}
header[data-testid="stHeader"]{background:transparent}
[data-testid="stSidebar"]{background:#070e1b;border-right:1px solid var(--line)}
.brand{font-weight:900;letter-spacing:.7px;font-size:1.25rem;background:linear-gradient(90deg,#56dcff,#8b7cff,#ff76cf);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.zhead{position:fixed;top:0;left:0;right:0;z-index:9999;background:rgba(5,10,20,.91);backdrop-filter:blur(18px);border-bottom:1px solid var(--line);padding:12px 22px;min-height:66px;display:flex;align-items:center;justify-content:space-between;gap:18px}
.head-brand{display:flex;align-items:center;gap:12px}.hamb{font-size:1.35rem;color:#bfeeff}
.metrics{display:flex;gap:26px;align-items:center;justify-content:flex-end;flex-wrap:wrap}.metric-label{font-size:.66rem;text-transform:uppercase;letter-spacing:.09em;color:#7287a3}.metric-value{font-weight:800;color:#f2f7ff;font-size:.92rem}
.card,.hero{background:linear-gradient(145deg,rgba(14,26,46,.94),rgba(8,18,33,.91));border:1px solid rgba(126,211,255,.12);border-radius:20px;padding:24px;margin-bottom:18px;box-shadow:0 18px 45px rgba(0,0,0,.25)}
.card:hover{border-color:rgba(86,220,255,.22)}.hero h1{margin:0 0 6px}.muted,.small{color:var(--muted)}
.footer{text-align:center;margin-top:48px;padding:28px 10px;color:#8193aa;border-top:1px solid rgba(255,255,255,.07)}
.wa{display:inline-block;margin-top:10px;padding:10px 17px;border-radius:12px;border:1px solid rgba(86,220,255,.28);background:rgba(86,220,255,.08);color:#9eeaff!important;text-decoration:none;font-weight:800}
.login-wrap{max-width:520px;margin:7vh auto}.login-brand{text-align:center;font-size:2rem}.typewriter{min-height:86px;text-align:center;font-size:1.35rem;font-weight:900;line-height:1.45;background:linear-gradient(90deg,#56dcff,#8b7cff,#ff76cf);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:22px 0 26px}
.section-title{font-size:1.1rem;font-weight:800;margin:2px 0 14px}.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#5ff2a8;box-shadow:0 0 12px #5ff2a8;margin-right:7px}
.stButton>button{border-radius:12px;border:1px solid rgba(86,220,255,.18);min-height:44px}.stButton>button:disabled{background:#172238!important;color:#596982!important}
textarea[aria-label="Enter Your Text"]{height:260px!important;max-height:260px!important;overflow-y:auto!important}
[data-testid="stMetric"]{background:rgba(14,26,46,.68);border:1px solid rgba(126,211,255,.10);border-radius:16px;padding:14px}
@media(max-width:760px){.block-container{padding-top:7rem}.zhead{padding:10px 12px;align-items:flex-start}.metrics{gap:9px;justify-content:flex-end}.metric-value{font-size:.76rem}.metric-label{font-size:.55rem}.head-brand .brand{font-size:1rem}.hero,.card{padding:18px;border-radius:16px}.login-wrap{margin:4vh auto}.typewriter{font-size:1.05rem}}
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

# -------------------- AUTH RESTORE --------------------
if not st.session_state.auth_session:
    sid=cookie_session_id()
    username=resolve_session(sid) if sid else None
    if username and username in user_db and not user_db[username].get("is_revoked",False):
        st.session_state.auth_session=True; st.session_state.current_user=username; st.session_state.session_id=sid; touch_session(sid)


def login_page():
    # Credentials are never written to query parameters.
    st.query_params.clear()
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
                sid=create_session(username); st.session_state.auth_session=True; st.session_state.current_user=username; st.session_state.session_id=sid; st.session_state.page="Dashboard"; set_cookie(sid); st.stop()
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
    st.query_params.clear(); clear_cookie()


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
    st.markdown(f'''<div class="zhead"><div class="head-brand"><span class="hamb">☰</span><span class="brand">{BRAND}</span></div>{metrics}</div>''',unsafe_allow_html=True)
    if page!="History" and not is_admin:
        iso=expiry_dt().isoformat()
        components.html(f'''<script>
        const ex=new Date("{iso}"); function t(){{let x=Math.max(0,Math.floor((ex-new Date())/1000));let d=Math.floor(x/86400);x%=86400;let h=Math.floor(x/3600);x%=3600;let m=Math.floor(x/60),s=x%60;let e=window.parent.document.getElementById('expiry-count');if(e)e.textContent=`${{d}} Days ${{h}} Hours ${{m}} Minutes ${{s}} Seconds`;}}t();setInterval(t,1000);
        </script>''',height=0)


def nav():
    with st.sidebar:
        st.markdown(f'<div class="brand" style="font-size:1.35rem">☰ {BRAND}</div>',unsafe_allow_html=True)
        st.caption(active_username.title())
        st.divider()
        for item in valid_pages:
            label=f'{PAGE_ICONS.get(item,"•")}  {item}'
            if st.button(label,use_container_width=True,key="nav_"+item,type="primary" if item==page else "secondary"):
                goto(item)
        st.divider()
        if st.button("Logout",use_container_width=True,key="logout_btn"):
            logout(); st.stop()


def footer():
    msg=quote(f"Hi, I want to know more about {BRAND}.")
    st.markdown(f'''<div class="footer"><div class="brand">{BRAND}</div><div class="small">{FOOTER_BY}</div><a class="wa" href="https://wa.me/{WHATSAPP_NUMBER_INTL}?text={msg}" target="_blank">💬 Contact on WhatsApp</a></div>''',unsafe_allow_html=True)

# -------------------- PAGE RENDERERS --------------------

def page_dashboard():
    header()
    st.markdown(f'<div class="hero"><h1>Welcome back, {html.escape(active_username.title())}</h1><p class="muted"><span class="status-dot"></span>Your creative workspace is ready.</p></div>',unsafe_allow_html=True)
    total=int(profile.get("total_credits_allocated",profile.get("total_limit",0))); rem=int(profile.get("remaining_chars",0)); exp=expiry_dt()
    a,b,c=st.columns(3); a.metric("Total Credits",f"{total:,}"); b.metric("Remaining Credits",f"{rem:,}"); c.metric("Plan Expiry",exp.strftime("%d %b %Y, %I:%M %p"))
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
            ext=Path(up.name).suffix.lower(); dest=voice_dir(active_username)/(safe_filename(clean)+ext); dest.write_bytes(up.getbuffer()); msg.info("Saving..."); bar.progress(100); st.session_state.vc_saving=False; st.success(f'Voice "{clean}" saved successfully.'); time.sleep(.2); st.rerun()
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
            if c2.button("Delete",key="confirm_"+v.name): v.unlink(missing_ok=True); st.session_state[confirm]=False; st.rerun()
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
    header(); st.markdown("## Turn Your Text Into Speech"); st.caption("Transform your text into natural, expressive speech using your selected voice.")
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
    clicked=st.button("Generate Speech",type="primary",use_container_width=True,disabled=bool(active) or count==0 or count>rem)
    if clicked and not active:
        gen_user=str(profile.get("kaggle_username","")).strip(); gen_token=str(profile.get("kaggle_token","")).strip()
        if not gen_user or not gen_token: st.error("Please connect your generation account in Settings before generating.")
        else:
            snapshot_title=title.strip() or "Untitled"; start_generation(active_username,text,snapshot_title,selected,gen_user,gen_token,count); st.rerun()
    st.markdown('</div>',unsafe_allow_html=True)
    if active:
        pct=float(active.get("progress",0)); st.markdown('<div class="card">',unsafe_allow_html=True); st.progress(int(pct)); st.markdown(f"**{pct:.1f}%** — {html.escape(active.get('message','Generating your speech...'))}"); st.caption("You can safely refresh this page. Your generation will continue."); st.markdown('</div>',unsafe_allow_html=True)
        if active.get("status")=="failed": st.error(active.get("error") or "Generation failed. Please try again.")
        else: time.sleep(1.2); st.rerun()
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
    header(); st.markdown("## Settings"); st.markdown('<div class="card">',unsafe_allow_html=True); st.markdown("### Generation Connection"); st.caption("Connect the account used to power your generations.")
    saved_u=profile.get("kaggle_username",""); saved_t=profile.get("kaggle_token","")
    show=st.checkbox("Show token",value=st.session_state.get("show_token",False)); st.session_state.show_token=show
    with st.form("connection_form"):
        u=st.text_input("Username",value=saved_u); t=st.text_input("API Token",value=saved_t,type="default" if show else "password"); a,b,c=st.columns(3); save=a.form_submit_button("Save Credentials",use_container_width=True); verify=b.form_submit_button("Verify Credentials",use_container_width=True); remove=c.form_submit_button("Remove Credentials",use_container_width=True)
    if save:
        if not u.strip() or not t.strip(): st.error("✕ Unable to save credentials. Please check your details and try again.")
        elif (profile.update({"kaggle_username":u.strip(),"kaggle_token":t.strip()}) or True) and push_database_updates(user_db): st.success("✓ Credentials saved successfully.")
        else: st.error("✕ Unable to save credentials. Please check your details and try again.")
    if verify:
        with st.spinner("Verifying..."): uok,tok,err=verify_generation_credentials(u.strip(),t.strip())
        if err: st.warning(err)
        else:
            st.write("✓ Username — Valid" if uok else "✕ Username — Invalid"); st.write("✓ API Token — Valid" if tok else "✕ API Token — Invalid")
            if uok and tok: st.success("Credentials verified successfully.")
    if remove: st.session_state.confirm_remove=True
    if st.session_state.get("confirm_remove"):
        st.warning("Remove your saved credentials? You will need to enter them again before using voice generation."); a,b=st.columns(2)
        if a.button("Cancel",key="cancel_remove"): st.session_state.confirm_remove=False; st.rerun()
        if b.button("Remove",key="remove_confirm"): profile["kaggle_username"]=""; profile["kaggle_token"]=""; ok=push_database_updates(user_db); st.session_state.confirm_remove=False; st.success("✓ Credentials removed successfully.") if ok else st.error("Unable to remove credentials."); st.rerun()
    st.markdown('</div>',unsafe_allow_html=True); footer()


def page_account():
    header(); st.markdown("## Account")
    st.markdown('<div class="card">',unsafe_allow_html=True); st.markdown("### Account Overview"); a,b=st.columns(2); a.metric("Username",active_username); a.metric("Total Credits",f'{int(profile.get("total_credits_allocated",profile.get("total_limit",0))):,}'); b.metric("Account Status","Active"); b.metric("Remaining Credits",f'{int(profile.get("remaining_chars",0)):,}'); st.caption(f'Expires: {expiry_dt().strftime("%d %b %Y, %I:%M %p")}'); st.markdown('</div>',unsafe_allow_html=True)
    st.markdown('<div class="card">',unsafe_allow_html=True); st.markdown("### Change Password")
    with st.form("change_password"):
        old=st.text_input("Current Password",type="password"); new=st.text_input("New Password",type="password"); change=st.form_submit_button("Change Password",use_container_width=True)
    if change:
        if profile.get("password")!=old: st.error("Current password is incorrect.")
        elif not new: st.error("Please enter a new password.")
        else: profile["password"]=new; st.success("Password changed successfully.") if push_database_updates(user_db) else st.error("Unable to change password right now.")
    st.markdown('</div>',unsafe_allow_html=True)
    st.markdown('<div class="card">',unsafe_allow_html=True); st.markdown("### Where Your Account Is Connected")
    current=st.session_state.get("session_id")
    for s in sessions_for_user(active_username):
        is_current=s["sid"]==current; ua=html.escape(s.get("user_agent","Unknown browser")); ip=html.escape(s.get("ip","Unavailable")); last=s.get("last_seen","—")
        st.markdown(f'<div class="card"><strong>{"This device" if is_current else "Other device"}</strong><div class="small">Browser / OS: {ua}</div><div class="small">IP: {ip}</div><div class="small">Last active: {html.escape(last)}</div></div>',unsafe_allow_html=True)
        if not is_current:
            key="remove_device_"+s["sid"]
            if st.button("Remove Access",key=key): st.session_state["confirm_device"]=s["sid"]
            if st.session_state.get("confirm_device")==s["sid"]:
                st.warning("Remove access from this device? This device will be logged out and its current session will no longer be valid."); a,b=st.columns(2)
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
nav();
if is_admin:
    routes={"Dashboard":admin_dashboard,"Active Users Registry":admin_registry,"Deploy New Client":admin_deploy,"Settings":admin_settings}
else:
    routes={"Dashboard":page_dashboard,"Voice Cloning":page_voice_cloning,"Text To Speech":page_tts,"History":page_history,"Settings":page_settings,"Account":page_account}

routes.get(page,routes[valid_pages[0]])()
