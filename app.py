import streamlit as st
import json
import os
import base64
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import requests
import time
import re

# ============================================================
# F5-TTS PREMIUM SAAS ENTERPRISE
# ============================================================

st.set_page_config(
    page_title="F5-TTS Premium SaaS Enterprise",
    page_icon="👑",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------- CONFIG --------------------

REPO_OWNER = "mfazil78761-glitch"
REPO_NAME = "F5-TTS-AK"
DB_URL = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/main/users_db.json"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/users_db.json"

GITHUB_PAT_TOKEN = str(st.secrets.get("GITHUB_PAT_TOKEN", "")).strip()

BASE_VOICE_DIR = Path("cloud_vault")
BASE_VOICE_DIR.mkdir(parents=True, exist_ok=True)

# -------------------- UI STYLE --------------------

st.markdown(
    """
<style>
.main {
    background: #0b1220;
}
.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
}
.hero {
    padding: 34px;
    border-radius: 22px;
    background: linear-gradient(135deg, #111827, #1e3a5f, #0f766e);
    color: white;
    margin-bottom: 24px;
    box-shadow: 0 10px 35px rgba(0,0,0,.25);
}
.card {
    padding: 22px;
    border-radius: 18px;
    background: rgba(30,41,59,.72);
    border: 1px solid rgba(255,255,255,.08);
    margin-bottom: 18px;
}
.small-muted {
    opacity: .75;
}
</style>
""",
    unsafe_allow_html=True,
)

# -------------------- GITHUB DATABASE --------------------

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
            "ngrok_auth_token": "",
            "ngrok_static_domain": "",
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


def push_database_updates_to_github(updated_db_dict):
    if not GITHUB_PAT_TOKEN:
        st.error(
            "GitHub PAT missing. Add GITHUB_PAT_TOKEN to Streamlit Secrets."
        )
        return False

    headers = {
        "Authorization": f"Bearer {GITHUB_PAT_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "F5-TTS-Cloud-App",
    }

    try:
        get_res = requests.get(
            GITHUB_API_URL,
            headers=headers,
            timeout=15,
        )

        if get_res.status_code != 200:
            st.error(
                f"GitHub database read failed: {get_res.status_code}"
            )
            return False

        sha = get_res.json().get("sha")

        content = json.dumps(
            {"users": updated_db_dict},
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")

        encoded_content = base64.b64encode(content).decode("ascii")

        payload = {
            "message": "Update users database from F5-TTS Web UI",
            "content": encoded_content,
            "sha": sha,
        }

        put_res = requests.put(
            GITHUB_API_URL,
            headers=headers,
            json=payload,
            timeout=15,
        )

        if put_res.status_code in (200, 201):
            return True

        st.error(
            f"GitHub database update failed: {put_res.status_code}"
        )
        return False

    except Exception as exc:
        st.error(f"GitHub update error: {exc}")
        return False


# -------------------- SESSION --------------------

user_db = fetch_live_database()

defaults = {
    "auth_session": False,
    "current_user": "",
    "current_password": "",
    "page": "Dashboard",
    "completed_audio": None,
    "completed_audio_chars": 0,
    "completed_audio_message": "",
}

for key, default in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default


# -------------------- LOGIN --------------------

query_params = st.query_params

if (
    not st.session_state.auth_session
    and "user" in query_params
    and "auth" in query_params
):
    u_state = query_params["user"]
    p_state = query_params["auth"]

    if (
        u_state in user_db
        and user_db[u_state].get("password") == p_state
    ):
        st.session_state.auth_session = True
        st.session_state.current_user = u_state
        st.session_state.current_password = p_state


if not st.session_state.auth_session:
    st.markdown(
        """
        <div class="hero">
            <h1>👑 F5-TTS Premium SaaS</h1>
            <p>Secure cloud voice cloning and text-to-speech workspace.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("secure_gateway"):
        username_input = st.text_input("Username").upper().strip()
        password_input = st.text_input("Password", type="password")

        login_triggered = st.form_submit_button(
            "🔐 Authorize Access",
            use_container_width=True,
        )

        if login_triggered:
            if username_input not in user_db:
                st.error("Unauthorized profile.")
            else:
                target_user = user_db[username_input]

                if target_user.get("is_revoked", False):
                    st.error("🚨 Your access is revoked.")
                elif target_user.get("password") != password_input:
                    st.error("Invalid password.")
                else:
                    exp_time = datetime.strptime(
                        target_user["expiry_timestamp"],
                        "%Y-%m-%d %H:%M:%S",
                    )

                    if (
                        exp_time < datetime.now()
                        and not target_user.get("is_admin", False)
                    ):
                        st.error("🚨 Your plan has expired.")
                    else:
                        st.session_state.auth_session = True
                        st.session_state.current_user = username_input
                        st.session_state.current_password = password_input
                        st.session_state.page = "Dashboard"

                        st.query_params["user"] = username_input
                        st.query_params["auth"] = password_input
                        st.rerun()

    st.stop()


# -------------------- ACTIVE PROFILE --------------------

active_username = st.session_state.current_user

if active_username not in user_db:
    st.session_state.auth_session = False
    st.query_params.clear()
    st.rerun()

account_profile = user_db[active_username]

if account_profile.get("is_revoked", False):
    st.session_state.auth_session = False
    st.query_params.clear()
    st.error("🚨 Access revoked by administrator.")
    st.stop()


# -------------------- HELPERS --------------------

def get_voice_dir():
    path = BASE_VOICE_DIR / active_username / "voices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_saved_voices():
    voice_dir = get_voice_dir()
    supported = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}

    return sorted(
        [
            p
            for p in voice_dir.iterdir()
            if p.is_file() and p.suffix.lower() in supported
        ],
        key=lambda p: p.name.lower(),
    )


def character_count(text):
    # Counts every Unicode character entered by the user,
    # including spaces and newline characters.
    return len(text)


def deduct_characters(amount):
    current = int(account_profile.get("remaining_chars", 0))

    if amount > current:
        return False

    account_profile["remaining_chars"] = current - amount
    return push_database_updates_to_github(user_db)


def save_kaggle_settings(username, token):
    account_profile["kaggle_username"] = username.strip()
    account_profile["kaggle_token"] = token.strip()
    account_profile.pop("ngrok_auth_token", None)
    account_profile.pop("ngrok_static_domain", None)
    return push_database_updates_to_github(user_db)


def generate_with_kaggle(text, voice_path, progress_callback=None):
    """Run one private Kaggle T4 batch F5-TTS job without ngrok."""
    def report(percent, message):
        if progress_callback is not None:
            try:
                progress_callback(percent, message)
            except Exception:
                pass

    try:
        report(5, "Checking Kaggle connection fields...")
        k_user = str(account_profile.get("kaggle_username", "")).strip()
        k_token = str(account_profile.get("kaggle_token", "")).strip()
        if not k_user:
            return None, "Kaggle Username is missing in Settings."
        if not k_token:
            return None, "Kaggle API Token is missing in Settings."

        voice_file = Path(voice_path)
        if not voice_file.exists() or voice_file.stat().st_size == 0:
            return None, "The selected reference voice file is missing or empty."

        voice_b64 = base64.b64encode(voice_file.read_bytes()).decode("ascii")
        text_json = json.dumps(text, ensure_ascii=False)
        raw_slug = f"f5tts-{active_username.lower()}-{uuid.uuid4().hex[:10]}"
        kernel_slug = "".join(c if c.isalnum() or c == "-" else "-" for c in raw_slug).strip("-")[:80]

        report(15, "Preparing the private Kaggle T4 batch worker...")
        workspace = Path(tempfile.mkdtemp(prefix="f5tts_kaggle_"))
        notebook_path = workspace / "active_worker.ipynb"
        metadata_path = workspace / "kernel-metadata.json"
        output_dir = Path(tempfile.mkdtemp(prefix="f5tts_kaggle_output_"))

        notebook_source = """import base64
import json
import subprocess
import sys
from pathlib import Path

OUTPUT = Path('/kaggle/working')
STATUS = OUTPUT / 'f5tts_status.json'
AUDIO = OUTPUT / 'generated.wav'
VOICE = OUTPUT / 'reference_voice.wav'

TEXT = __TEXT_JSON__
VOICE_B64 = __VOICE_B64__


def write_status(status, message='', percent=None, chunk=None, total_chunks=None):
    payload = {
        'status': status,
        'message': message,
    }
    if percent is not None:
        payload['percent'] = float(percent)
    if chunk is not None:
        payload['chunk'] = int(chunk)
    if total_chunks is not None:
        payload['total_chunks'] = int(total_chunks)
    STATUS.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


class LiveChunkProgress:
    # Bridge F5-TTS's real chunk progress to Kaggle logs.
    # F5-TTS internally creates text batches and passes those batches through
    # tqdm. Wrapping that iterator lets us report only completed chunks, so the
    # percentage is real progress rather than a timer-based estimate.
    def tqdm(self, iterable, *args, **kwargs):
        items = list(iterable)
        total = len(items)
        if total == 0:
            return
        for index, item in enumerate(items, 1):
            yield item
            percent = (index / total) * 100.0
            write_status(
                'generating',
                f'F5-TTS completed chunk {index}/{total}',
                percent=percent,
                chunk=index,
                total_chunks=total,
            )
            print(
                f'F5-TTS CHUNK {index}/{total} {percent:.1f}%',
                flush=True,
            )


try:
    write_status('starting', 'Preparing F5-TTS on Kaggle GPU', percent=0)
    VOICE.write_bytes(base64.b64decode(VOICE_B64))
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'f5-tts'])
    write_status('generating', 'F5-TTS generation started on the Kaggle T4', percent=0)
    print('F5-TTS GENERATION STARTED 0.0%', flush=True)

    from f5_tts.api import F5TTS

    tts = F5TTS(model='F5TTS_v1_Base', device='cuda')
    progress = LiveChunkProgress()

    tts.infer(
        ref_file=str(VOICE),
        ref_text='',
        gen_text=TEXT,
        progress=progress,
        file_wave=str(AUDIO),
        remove_silence=False,
    )

    if not AUDIO.exists() or AUDIO.stat().st_size < 1000:
        raise RuntimeError('F5-TTS finished without producing a valid WAV file.')

    write_status(
        'success',
        'Audio generated successfully',
        percent=100.0,
    )
    print('F5-TTS GENERATION COMPLETE 100.0%', flush=True)
    print('F5-TTS audio generated:', AUDIO.stat().st_size, 'bytes', flush=True)
except Exception as exc:
    message = repr(exc)
    write_status('error', message)
    print('F5-TTS generation error:', message, flush=True)
"""
        notebook_source = notebook_source.replace('__TEXT_JSON__', text_json).replace('__VOICE_B64__', repr(voice_b64))

        notebook = {
            "cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": notebook_source.splitlines(True)}],
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        notebook_path.write_text(json.dumps(notebook, indent=2, ensure_ascii=False), encoding="utf-8")

        metadata = {
            "id": f"{k_user}/{kernel_slug}",
            "title": kernel_slug,
            "code_file": "active_worker.ipynb",
            "language": "python",
            "kernel_type": "notebook",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": True,
            "machine_shape": "NvidiaTeslaT4",
            "dataset_sources": [],
            "competition_sources": [],
            "kernel_sources": [],
            "model_sources": [],
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        report(35, "Worker package is ready. Connecting to your Kaggle account...")
        env = os.environ.copy()
        env["KAGGLE_USERNAME"] = k_user
        env["KAGGLE_API_TOKEN"] = k_token
        env["KAGGLE_KEY"] = k_token

        report(50, "Uploading the notebook and requesting the Kaggle T4 GPU...")
        completed = subprocess.run(["kaggle", "kernels", "push", "-p", str(workspace)], env=env, capture_output=True, text=True, check=False)
        combined_output = ((completed.stdout or "").strip() + "\n" + (completed.stderr or "").strip()).strip()
        if completed.returncode != 0:
            report(100, "Kaggle rejected the GPU worker request.")
            return None, f"Kaggle kernel push failed (exit code {completed.returncode}).\n{combined_output}"

        kernel_ref = f"{k_user}/{kernel_slug}"
        report(60, "Kaggle accepted the notebook. Waiting for the T4 job...")
        final_state = ""
        last_status = ""
        worker_generation_started = False
        last_worker_progress = 0
        log_restart_count = 0

        # IMPORTANT: there is deliberately NO application-level generation
        # timeout here. We stream Kaggle's live kernel log until Kaggle closes
        # the log stream, then download the output. This prevents a long 25-30
        # minute narration from being mistaken for a failed generation.
        # `kernels status` is intentionally not used because this deployment
        # previously returned GetKernelSessionStatus HTTP 404.
        import select

        def probe_kaggle_output():
            """Check whether Kaggle has produced the final/status files yet.

            This is a completion probe only; it is never given an application
            timeout. A missing output simply means the worker is still running.
            """
            probe_dir = Path(tempfile.mkdtemp(prefix="f5tts_probe_"))
            try:
                probe = subprocess.run(
                    ["kaggle", "kernels", "output", kernel_ref, "-p", str(probe_dir), "-o", "-q"],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                probe_text = ((probe.stdout or "") + "\n" + (probe.stderr or "")).strip()
                status_candidates = list(probe_dir.rglob("f5tts_status.json"))
                audio_candidates = list(probe_dir.rglob("generated.wav"))
                status_payload = None
                if status_candidates:
                    try:
                        status_payload = json.loads(status_candidates[0].read_text(encoding="utf-8"))
                    except Exception:
                        status_payload = {"status": "unreadable", "message": "Could not read f5tts_status.json"}
                audio_ready = bool(audio_candidates)
                return probe.returncode, probe_text[-3000:], status_payload, audio_ready
            finally:
                import shutil
                shutil.rmtree(probe_dir, ignore_errors=True)

        while True:
            # Re-attach to the live log stream whenever the Kaggle CLI closes
            # its stream unexpectedly. A CLI stream ending is NOT treated as
            # a T4 failure; the worker itself is the source of truth.
            log_process = subprocess.Popen(
                ["kaggle", "kernels", "logs", kernel_ref, "--follow"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            stream_closed = False
            try:
                while True:
                    ready, _, _ = select.select([log_process.stdout], [], [], 2.0)
                    if ready:
                        line = log_process.stdout.readline()
                        if line:
                            last_status = (last_status + "\n" + line.strip())[-5000:]
                            log_upper = line.upper()

                            if any(marker in log_upper for marker in (
                                "KERNEL FAILED", "KERNEL ERROR", "TRACEBACK", "RUNTIMEERROR",
                                "EXCEPTION", "CANCELLED", "CANCELED", "FAILED TO RUN"
                            )):
                                final_state = "error"
                                break

                            # Prefer the explicit chunk-progress line emitted by
                            # the Kaggle worker. This is real completed-chunk
                            # progress from F5-TTS, not elapsed-time estimation.
                            chunk_match = re.search(
                                r"F5-TTS CHUNK\s+(\d+)\s*/\s*(\d+)\s+(\d+(?:\.\d+)?)%",
                                line,
                                flags=re.IGNORECASE,
                            )
                            parsed_percent = None
                            if chunk_match:
                                parsed_percent = float(chunk_match.group(3))
                                worker_generation_started = True

                            if parsed_percent is None:
                                percent_matches = re.findall(
                                    r"(?:\[|\s|^)(\d{1,3}(?:\.\d+)?)%",
                                    line,
                                )
                                for raw_percent in reversed(percent_matches):
                                    value = float(raw_percent)
                                    if 0 <= value <= 100:
                                        parsed_percent = value
                                        break

                            if any(marker in log_upper for marker in (
                                "F5-TTS MODEL IS RUNNING", "STARTING F5-TTS",
                                "F5-TTS GENERATION STARTED", "INFER", "GENERATING"
                            )):
                                worker_generation_started = True

                            if parsed_percent is not None and worker_generation_started:
                                last_worker_progress = parsed_percent
                                report(
                                    parsed_percent,
                                    f"🎙️ Voice generation: {parsed_percent:.1f}% complete",
                                )
                            elif worker_generation_started:
                                report(max(1, last_worker_progress), "🎙️ F5-TTS is generating on the Kaggle T4...")
                            else:
                                report(15, "⏳ Kaggle T4 is starting the F5-TTS worker...")
                        else:
                            stream_closed = True
                            break
                    elif log_process.poll() is not None:
                        stream_closed = True
                        break

                    if worker_generation_started:
                        report(max(1, last_worker_progress), "🎙️ F5-TTS is still generating on the Kaggle T4...")
                    else:
                        report(15, "⏳ Kaggle T4 is starting the F5-TTS worker...")
            finally:
                if log_process.stdout:
                    log_process.stdout.close()
                if log_process.poll() is None:
                    log_process.terminate()
                    log_process.wait()

            if final_state == "error":
                break

            # The logs command may close even while the remote kernel is still
            # running. Probe for actual worker output before deciding anything.
            probe_rc, probe_text, status_payload, probe_audio = probe_kaggle_output()
            if status_payload or probe_audio:
                if status_payload:
                    status_value = status_payload.get("status")
                    if status_value == "error":
                        final_state = "error"
                        last_status = (last_status + "\n" + str(status_payload.get("message", "Unknown F5-TTS error")))[-5000:]
                        break
                    if status_value == "success" and probe_audio:
                        final_state = "complete"
                        break
                if probe_audio:
                    final_state = "complete"
                    break

            log_restart_count += 1
            report(max(15, last_worker_progress), f"🔄 Reconnecting to Kaggle T4 live logs... (attempt {log_restart_count})")
            time.sleep(2)

        if final_state == "error":
            report(max(1, last_worker_progress), "❌ F5-TTS worker reported an error.")
            return None, "Kaggle T4 job reported an error or was cancelled.\n\n" + last_status

        # The log stream ended normally. Now retrieve the completed output.
        report(max(85, last_worker_progress), "📦 Kaggle T4 finished. Retrieving the generated WAV...")
        download = subprocess.run(["kaggle", "kernels", "output", kernel_ref, "-p", str(output_dir), "-o", "-q"], env=env, capture_output=True, text=True, check=False)
        if download.returncode != 0:
            details = ((download.stdout or "") + "\n" + (download.stderr or "")).strip()
            return None, "Kaggle finished the worker, but its output could not be downloaded.\n" + details[:5000]

        final_state = "complete"
        status_files = list(output_dir.rglob("f5tts_status.json"))
        if status_files:
            try:
                status_payload = json.loads(status_files[0].read_text(encoding="utf-8"))
            except Exception:
                status_payload = {}
            if status_payload.get("status") != "success":
                return None, "F5-TTS ran on Kaggle but reported an error:\n" + str(status_payload.get("message", "Unknown F5-TTS error"))

        audio_files = list(output_dir.rglob("generated.wav"))
        if not audio_files:
            return None, "Kaggle completed successfully, but generated.wav was not found in the notebook output."
        audio_bytes = audio_files[0].read_bytes()
        if len(audio_bytes) < 1000 or not audio_bytes.startswith(b"RIFF"):
            return None, "Kaggle returned generated.wav, but it is not a valid WAV file."
        report(100, "F5-TTS generated the audio successfully on Kaggle T4.")
        return audio_bytes, None

    except FileNotFoundError:
        report(100, "Kaggle CLI is not installed on the Streamlit server.")
        return None, "Kaggle CLI was not found on the Streamlit server. Install it with: pip install kaggle"
    except Exception as exc:
        report(100, "The Kaggle T4 job stopped with an unexpected error.")
        return None, f"Kaggle infrastructure error: {exc}"



# -------------------- SIDEBAR --------------------

with st.sidebar:
    st.markdown("## 👑 F5-TTS")
    st.write(f"**User:** {active_username}")

    if account_profile.get("is_admin", False):
        st.info("Master Administrator")

        admin_page = st.radio(
            "Navigation",
            [
                "Dashboard",
                "Active Users Registry",
                "Deploy New SaaS Client",
                "Settings",
            ],
            key="admin_navigation",
        )

        st.session_state.page = admin_page

    else:
        st.info("Authorized Client")

        client_page = st.radio(
            "Navigation",
            [
                "Dashboard",
                "🎤 Voice Cloning",
                "🔊 Text To Speech",
                "⚙️ Settings",
            ],
            key="client_navigation",
        )

        st.session_state.page = client_page

    st.divider()

    if st.button(
        "🔒 Terminate Secure Session",
        use_container_width=True,
    ):
        st.session_state.auth_session = False
        st.session_state.current_user = ""
        st.session_state.current_password = ""
        st.query_params.clear()
        st.rerun()


page = st.session_state.page


# ============================================================
# DASHBOARD
# ============================================================

if page == "Dashboard":
    st.markdown(
        f"""
        <div class="hero">
            <h1>Welcome, {active_username.upper()} 👋</h1>
            <p>
                Your F5-TTS cloud workspace is ready.
                Manage voices, generate speech and configure your account
                from one place.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)

    remaining = int(account_profile.get("remaining_chars", 0))
    total = int(account_profile.get("total_limit", 0))

    with col1:
        st.metric("Characters Remaining", f"{remaining:,}")

    with col2:
        st.metric("Total Allocation", f"{total:,}")

    with col3:
        st.metric(
            "Saved Voices",
            len(get_saved_voices()),
        )

    st.markdown(
        """
        <div class="card">
            <h2>🚀 Get Started</h2>
            <p class="small-muted">
                Upload a reference voice first, give it a name, then select
                that saved voice from the Text To Speech page.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        "🚀 Get Started — Voice Cloning",
        type="primary",
        use_container_width=True,
    ):
        st.session_state.page = "🎤 Voice Cloning"
        st.rerun()


# ============================================================
# VOICE CLONING
# ============================================================

elif page == "🎤 Voice Cloning":
    st.title("🎤 Voice Cloning")
    st.caption(
        "Upload a reference voice and save it with your own voice name."
    )

    st.markdown(
        '<div class="card">',
        unsafe_allow_html=True,
    )

    voice_name = st.text_input(
        "Voice Name",
        placeholder="Example: My Voice",
        max_chars=80,
    )

    uploaded_voice = st.file_uploader(
        "Upload Reference Voice",
        type=["wav", "mp3", "m4a", "ogg", "flac"],
    )

    save_voice = st.button(
        "💾 Save Voice",
        type="primary",
        use_container_width=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)

    if save_voice:
        clean_name = voice_name.strip()

        if not clean_name:
            st.error("Please enter a voice name.")
        elif uploaded_voice is None:
            st.error("Please upload a voice file.")
        else:
            safe_name = "".join(
                c
                if c.isalnum() or c in (" ", "_", "-")
                else "_"
                for c in clean_name
            ).strip()

            if not safe_name:
                st.error("Invalid voice name.")
            else:
                extension = Path(uploaded_voice.name).suffix.lower()
                destination = get_voice_dir() / f"{safe_name}{extension}"

                destination.write_bytes(
                    uploaded_voice.getbuffer()
                )

                st.success(
                    f'Voice "{clean_name}" saved successfully.'
                )
                st.rerun()

    voices = get_saved_voices()

    if voices:
        st.subheader("Your Saved Voices")

        for voice in voices:
            st.write(
                f"🎙️ **{voice.stem}** — `{voice.name}`"
            )
    else:
        st.info("No saved voices yet.")


# ============================================================
# TEXT TO SPEECH
# ============================================================

elif page == "🔊 Text To Speech":
    st.title("🔊 Text To Speech")

    if st.session_state.get("completed_audio"):
        st.success(st.session_state.get("completed_audio_message", "Audio generated successfully."))
        st.audio(st.session_state.completed_audio, format="audio/wav")

    voices = get_saved_voices()

    if not voices:
        st.warning(
            "No saved voice found. Go to Voice Cloning and save a voice first."
        )

        if st.button("🎤 Open Voice Cloning"):
            st.session_state.page = "🎤 Voice Cloning"
            st.rerun()

    else:
        voice_names = [v.stem for v in voices]

        selected_voice = st.selectbox(
            "🎙️ My Voice",
            voice_names,
        )

        selected_path = next(
            p for p in voices if p.stem == selected_voice
        )

        st.caption(
            f"Selected voice: {selected_path.name}"
        )

        text_input = st.text_area(
            "Enter Text",
            height=260,
            placeholder="Type your text here...",
        )

        current_count = character_count(text_input)
        remaining = int(
            account_profile.get("remaining_chars", 0)
        )

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "Current Characters",
                f"{current_count:,}",
            )

        with col2:
            st.metric(
                "Balance After Generation",
                f"{max(remaining - current_count, 0):,}",
            )

        if current_count > remaining:
            st.error(
                "Not enough characters in your balance."
            )

        generate = st.button(
            "⚡ Generate",
            type="primary",
            use_container_width=True,
        )

        if generate:
            if not text_input:
                st.error("Please enter text.")

            elif current_count > remaining:
                st.error(
                    "Character balance is insufficient."
                )

            else:
                progress_box = st.empty()
                progress_percent_box = st.empty()
                progress_bar = st.progress(0)
                status_box = st.empty()

                def generation_progress(percent, message):
                    # Streamlit's progress bar takes an integer, while the
                    # label below it shows the exact live percentage (for
                    # example 2.4%, 37.8%, 81.3%).
                    safe_percent = max(0.0, min(100.0, float(percent)))
                    progress_bar.progress(int(safe_percent))
                    progress_percent_box.markdown(
                        f"### 🎙️ {safe_percent:.1f}%"
                    )
                    status_box.info(
                        f"🔄 {message}"
                    )

                generation_progress(
                    2,
                    "Generation request started. Do not close this page.",
                )

                with st.status(
                    "⚙️ F5-TTS generation in progress...",
                    expanded=True,
                ) as generation_status:
                    generated, error = generate_with_kaggle(
                        text_input,
                        selected_path,
                        progress_callback=generation_progress,
                    )

                    if error:
                        generation_status.update(
                            label="❌ Generation stopped",
                            state="error",
                            expanded=True,
                        )
                        progress_bar.progress(0)
                        status_box.error(
                            "The request did not complete. See the diagnostic below."
                        )
                        st.error(error)
                        st.code(
                            error,
                            language="text",
                        )

                    else:
                        generation_status.update(
                            label="✅ Kaggle worker accepted the request",
                            state="complete",
                            expanded=True,
                        )

                        # Only charge the wallet when an actual audio
                        # result was returned. A workspace URL alone is
                        # not proof that audio was generated.
                        audio_received = False

                        if isinstance(generated, bytes):
                            audio_received = True
                            st.audio(
                                generated,
                                format="audio/wav",
                            )

                        elif isinstance(generated, dict):
                            audio_url = generated.get(
                                "audio_url"
                            )

                            if audio_url:
                                audio_received = True
                                st.audio(audio_url)
                            else:
                                st.json(generated)

                        elif isinstance(generated, str):
                            st.warning(
                                "⚠️ Kaggle accepted the worker, but this request "
                                "returned only the workspace URL — no audio file "
                                "was returned yet."
                            )
                            st.markdown(
                                f"**Secure workspace:** [{generated}]({generated})"
                            )

                        if audio_received:
                            if deduct_characters(current_count):
                                st.success(
                                    f"✅ Audio generated successfully. "
                                    f"{current_count:,} characters deducted."
                                )
                                status_box.success(
                                    "✅ Audio output received and wallet updated."
                                )
                            else:
                                st.error(
                                    "Audio was generated, but the character "
                                    "balance could not be updated. Contact the administrator."
                                )
                                status_box.warning(
                                    "⚠️ Audio received, but wallet update failed."
                                )
                        else:
                            status_box.warning(
                                "⚠️ No audio file was returned, so no characters were deducted."
                            )

                        progress_box.empty()



# ============================================================
# SETTINGS
# ============================================================

elif page in ("⚙️ Settings", "Settings"):
    if (
        page == "Settings"
        and not account_profile.get("is_admin", False)
    ):
        st.title("⚙️ Settings")
    elif page == "⚙️ Settings":
        st.title("⚙️ Settings")
    else:
        st.title("⚙️ Administrator Settings")

    if account_profile.get("is_admin", False):
        st.info(
            "System-level GITHUB_PAT_TOKEN remains in Streamlit Secrets."
        )
    else:
        st.subheader("Kaggle GPU Connection")
        st.info("Enter your Kaggle Username and Kaggle API Token. Ngrok is no longer required.")
        saved_username = account_profile.get("kaggle_username", "")
        saved_token = account_profile.get("kaggle_token", "")
        with st.form("kaggle_settings_form"):
            kaggle_username = st.text_input("Kaggle Username", value=saved_username)
            kaggle_token = st.text_input("Kaggle API Token", value=saved_token, type="password")
            save_kaggle = st.form_submit_button("💾 Save Connection Settings", use_container_width=True)
            if save_kaggle:
                if not kaggle_username.strip() or not kaggle_token.strip():
                    st.error("Enter Kaggle Username and Kaggle API Token.")
                elif save_kaggle_settings(kaggle_username, kaggle_token):
                    st.success("Kaggle GPU settings saved. Ngrok has been removed.")
                    st.rerun()


# ============================================================
# ADMIN USER REGISTRY
# ============================================================

elif page == "Active Users Registry":
    if not account_profile.get("is_admin", False):
        st.error("Administrator access required.")
        st.stop()

    st.title("👑 Active Users Registry")

    regular_users = [
        (name, info)
        for name, info in user_db.items()
        if not info.get("is_admin", False)
    ]

    if not regular_users:
        st.info(
            "No regular users are registered."
        )

    for u_name, u_info in regular_users:
        with st.expander(
            f"{u_name} — "
            f"{'🔴 Revoked' if u_info.get('is_revoked') else '🟢 Active'}"
        ):
            new_limit = st.number_input(
                "Remaining Characters",
                min_value=0,
                value=int(
                    u_info.get(
                        "remaining_chars",
                        0,
                    )
                ),
                key=f"limit_{u_name}",
            )

            add_days = st.number_input(
                "Extend Plan Days",
                min_value=0,
                value=0,
                key=f"days_{u_name}",
            )

            col1, col2 = st.columns(2)

            with col1:
                if st.button(
                    "🔴 Revoke / 🟢 Grant",
                    key=f"toggle_{u_name}",
                    use_container_width=True,
                ):
                    u_info["is_revoked"] = not u_info.get(
                        "is_revoked",
                        False,
                    )

                    if push_database_updates_to_github(
                        user_db
                    ):
                        st.rerun()

            with col2:
                if st.button(
                    "💾 Save Changes",
                    key=f"save_{u_name}",
                    use_container_width=True,
                ):
                    u_info["remaining_chars"] = int(
                        new_limit
                    )

                    if add_days > 0:
                        curr_exp = datetime.strptime(
                            u_info["expiry_timestamp"],
                            "%Y-%m-%d %H:%M:%S",
                        )

                        if curr_exp < datetime.now():
                            curr_exp = datetime.now()

                        u_info["expiry_timestamp"] = (
                            curr_exp
                            + timedelta(
                                days=int(add_days)
                            )
                        ).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )

                    if push_database_updates_to_github(
                        user_db
                    ):
                        st.rerun()


# ============================================================
# ADMIN DEPLOY
# ============================================================

elif page == "Deploy New SaaS Client":
    if not account_profile.get("is_admin", False):
        st.error("Administrator access required.")
        st.stop()

    st.title("➕ Deploy New SaaS Client")

    with st.form(
        "new_user_registration_form"
    ):
        reg_user = st.text_input(
            "New Client Username"
        ).upper().strip()

        reg_pass = st.text_input(
            "Set Login Password",
            type="password",
        )

        reg_days = st.number_input(
            "Plan Duration (Days)",
            min_value=1,
            value=30,
        )

        reg_chars = st.number_input(
            "Character Allocation",
            min_value=1000,
            value=1000000,
        )

        create_user = st.form_submit_button(
            "🚀 Deploy User",
            use_container_width=True,
        )

        if create_user:
            if not reg_user or not reg_pass:
                st.error(
                    "Username and password are required."
                )

            elif reg_user in user_db:
                st.error(
                    "That username already exists."
                )

            else:
                expiry = (
                    datetime.now()
                    + timedelta(
                        days=int(reg_days)
                    )
                ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                user_db[reg_user] = {
                    "password": reg_pass,
                    "expiry_timestamp": expiry,
                    "total_limit": int(reg_chars),
                    "remaining_chars": int(reg_chars),
                    "is_revoked": False,
                    "is_admin": False,
                    "kaggle_username": "",
                    "kaggle_token": "",
                    "ngrok_auth_token": "",
                    "ngrok_static_domain": "",
                }

                if push_database_updates_to_github(
                    user_db
                ):
                    st.success(
                        f"User {reg_user} created successfully."
                    )
                    st.rerun()


# -------------------- FOOTER --------------------

st.markdown("---")
st.caption(
    "F5-TTS Premium SaaS Enterprise • Secure user workspace"
)
