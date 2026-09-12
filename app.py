import os
import uuid
import glob
import json
import subprocess
import threading
import sys
import shutil
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_file, render_template

app = Flask(__name__)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(APP_DIR, "downloads")
HISTORY_FILE = os.path.join(APP_DIR, "history.json")
COOKIE_FILE = os.path.join(APP_DIR, "cookies.txt")
INFO_TIMEOUT = int(os.environ.get("YTDLP_INFO_TIMEOUT", "180"))
DOWNLOAD_TIMEOUT = int(os.environ.get("YTDLP_DOWNLOAD_TIMEOUT", "600"))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(sys.executable))
YTDLP = os.path.join(SCRIPTS_DIR, "yt-dlp.exe")
FFMPEG_DIR = SCRIPTS_DIR
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Helper to find yt-dlp executable
def get_ytdlp_path():
    # 1. Check if we're in a venv and yt-dlp is there
    venv_bin = "Scripts" if os.name == "nt" else "bin"
    venv_exe = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    
    # Try looking in the current python's directory (standard for venv)
    local_path = os.path.join(os.path.dirname(sys.executable), venv_exe)
    if os.path.exists(local_path):
        return local_path
        
    # 2. Try looking in a .venv or venv folder in the project root
    for venv_name in [".venv", "venv"]:
        path = os.path.join(os.path.dirname(__file__), venv_name, venv_bin, venv_exe)
        if os.path.exists(path):
            return path
            
    # 3. Fallback to system path
    return "yt-dlp"

YTDLP = get_ytdlp_path()
jobs = {}
history_lock = threading.Lock()


def yt_dlp_command(*args):
    executable = YTDLP if os.path.exists(YTDLP) else "yt-dlp"
    cmd = [executable]
    if os.path.isfile(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        cmd += ["--cookies", COOKIE_FILE]
    if shutil.which("node"):
        cmd += ["--js-runtimes", "node"]
    cmd += ["--ffmpeg-location", FFMPEG_DIR, "--no-playlist", *args]
    return cmd


def command_error(result):
    lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    error_lines = [line for line in lines if "ERROR:" in line]
    if error_lines:
        return error_lines[-1]
    return (lines or ["yt-dlp failed"])[-1]


def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(entries):
    temp_file = f"{HISTORY_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(temp_file, HISTORY_FILE)


def add_history(job_id, job):
    entry = {
        "id": job_id,
        "url": job["url"],
        "title": job.get("title") or "Untitled",
        "thumbnail": job.get("thumbnail", ""),
        "uploader": job.get("uploader", ""),
        "duration": job.get("duration"),
        "format": job.get("format", "video"),
        "filename": job["filename"],
        "file": job["file"],
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    with history_lock:
        entries = [item for item in load_history() if item.get("id") != job_id]
        entries.insert(0, entry)
        save_history(entries[:100])


def public_history(entry):
    item = {key: value for key, value in entry.items() if key != "file"}
    item["file_available"] = os.path.isfile(entry.get("file", ""))
    return item


def get_ffmpeg_path():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FFMPEG = get_ffmpeg_path()


def run_download(job_id, url, format_choice, format_id):
    job = jobs[job_id]
    out_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    cmd = yt_dlp_command("-o", out_template)

    if format_choice == "audio":
        cmd += ["-x", "--audio-format", "mp3"]
    elif format_id:
        cmd += ["-f", f"{format_id}+bestaudio/best", "--merge-output-format", "mp4"]
    else:
        cmd += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]

    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT)
        if result.returncode != 0:
            job["status"] = "error"
            job["error"] = command_error(result)
            return

        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{job_id}.*"))
        if not files:
            job["status"] = "error"
            job["error"] = "Download completed but no file was found"
            return

        if format_choice == "audio":
            target = [f for f in files if f.endswith(".mp3")]
            chosen = target[0] if target else files[0]
        else:
            target = [f for f in files if f.endswith(".mp4")]
            chosen = target[0] if target else files[0]

        for f in files:
            if f != chosen:
                try:
                    os.remove(f)
                except OSError:
                    pass

        job["status"] = "done"
        job["file"] = chosen
        ext = os.path.splitext(chosen)[1]
        title = job.get("title", "").strip()
        # Sanitize title for filename
        if title:
            safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:20].strip()
            job["filename"] = f"{safe_title}{ext}" if safe_title else os.path.basename(chosen)
        else:
            job["filename"] = os.path.basename(chosen)
        add_history(job_id, job)
    except subprocess.TimeoutExpired:
        job["status"] = "error"
        job["error"] = "Download timed out (5 min limit)"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    cmd = yt_dlp_command("--skip-download", "--dump-single-json", url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=INFO_TIMEOUT)
        if result.returncode != 0:
            return jsonify({"error": command_error(result)}), 400

        info = json.loads(result.stdout)

        # Build quality options — keep best format per resolution
        best_by_height = {}
        for f in info.get("formats", []):
            height = f.get("height")
            if height and f.get("vcodec", "none") != "none":
                tbr = f.get("tbr") or 0
                if height not in best_by_height or tbr > (best_by_height[height].get("tbr") or 0):
                    best_by_height[height] = f

        formats = []
        for height, f in best_by_height.items():
            formats.append({
                "id": f["format_id"],
                "label": f"{height}p",
                "height": height,
            })
        formats.sort(key=lambda x: x["height"], reverse=True)

        return jsonify({
            "title": info.get("title", ""),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration"),
            "uploader": info.get("uploader", ""),
            "formats": formats,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching video info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json
    url = data.get("url", "").strip()
    format_choice = data.get("format", "video")
    format_id = data.get("format_id")
    title = data.get("title", "")
    thumbnail = data.get("thumbnail", "")
    uploader = data.get("uploader", "")
    duration = data.get("duration")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {
        "status": "downloading",
        "url": url,
        "title": title,
        "thumbnail": thumbnail,
        "uploader": uploader,
        "duration": duration,
        "format": format_choice,
    }

    thread = threading.Thread(target=run_download, args=(job_id, url, format_choice, format_id))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def check_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "error": job.get("error"),
        "filename": job.get("filename"),
    })


@app.route("/api/file/<job_id>")
def download_file(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404
    return send_file(job["file"], as_attachment=True, download_name=job["filename"])


@app.route("/api/history")
def get_history():
    with history_lock:
        return jsonify([public_history(entry) for entry in load_history()])


@app.route("/api/history/<history_id>/file")
def download_history_file(history_id):
    with history_lock:
        entry = next((item for item in load_history() if item.get("id") == history_id), None)
    if not entry or not os.path.isfile(entry.get("file", "")):
        return jsonify({"error": "Downloaded file is no longer available"}), 404
    return send_file(entry["file"], as_attachment=True, download_name=entry["filename"])


@app.route("/api/history/<history_id>", methods=["DELETE"])
def delete_history(history_id):
    with history_lock:
        entries = load_history()
        updated = [item for item in entries if item.get("id") != history_id]
        if len(updated) == len(entries):
            return jsonify({"error": "History item not found"}), 404
        save_history(updated)
    return jsonify({"ok": True})


@app.route("/api/history", methods=["DELETE"])
def clear_history():
    with history_lock:
        save_history([])
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port)
