"""Shared helpers for the facts-shorts factory."""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H, FPS = 1080, 1920, 30
UA = "facts-shorts-factory/1.0"


def log(msg):
    print(msg, flush=True)


def die(msg):
    print(f"::error::{msg}", flush=True)
    sys.exit(1)


def env(name, required=True):
    val = os.environ.get(name, "").strip()
    if required and not val:
        die(f"missing secret {name} - add it in GitHub Settings > Secrets > Actions")
    return val


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def http(url, data=None, headers=None, method=None, timeout=120):
    hdrs = {"User-Agent": UA}
    hdrs.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download(url, dest):
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(http(url, timeout=300))
    return dest


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        log(p.stderr[-3000:])
        die(f"command failed: {' '.join(map(str, cmd[:6]))} ...")
    return p


def probe_duration(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    return float(p.stdout.strip())


def q(s):
    return urllib.parse.quote_plus(s)


def episode_dir(ep_id):
    return ROOT / "work" / ep_id
