"""Stage 1: narration + footage candidates + contact sheets for review.

usage: python factory/fetch.py ep001
"""
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import footage
import voice
from common import (ROOT, download, episode_dir, http, env, load_json, log, run,
                    save_json)

TILE_W, TILE_H = 300, 300


def line_spans(lines, words):
    """Map each script line to its word index range."""
    counts = [len(l["text"].split()) for l in lines]
    if sum(counts) != len(words):
        log(f"word count mismatch ({sum(counts)} vs {len(words)}); scaling")
        scale = len(words) / sum(counts)
        counts = [max(1, round(c * scale)) for c in counts]
        counts[-1] = len(words) - sum(counts[:-1])
    spans, i = [], 0
    for c in counts:
        spans.append((i, i + c - 1))
        i += c
    return spans


def make_sfx():
    sfx_dir = ROOT / "assets" / "sfx"
    wanted = {
        "whoosh.mp3": ("fast clean cinematic whoosh transition, short, no music", 0.8),
        "hit.mp3": ("deep soft cinematic boom impact, subtle, no music", 1.2),
        "pop.mp3": ("tiny soft bubble pop click for subtitle, very short", 0.5),
    }
    for name, (prompt, dur) in wanted.items():
        out = sfx_dir / name
        if out.exists():
            continue
        try:
            audio = http("https://api.elevenlabs.io/v1/sound-generation",
                         data={"text": prompt, "duration_seconds": dur, "prompt_influence": 0.6},
                         headers={"xi-api-key": env("ELEVENLABS_API_KEY")}, method="POST")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(audio)
            log(f"sfx created: {name}")
        except Exception as e:
            log(f"::warning::sound effect {name} not created ({e}); clip will use no SFX for it")


def frame_from(url, tmp):
    src = download(url, Path(tmp) / (str(abs(hash(url))) + ".mp4"))
    out = Path(tmp) / (src.stem + ".jpg")
    run(["ffmpeg", "-y", "-v", "error", "-ss", "1.5", "-i", str(src), "-frames:v", "1",
         "-vf", f"scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=increase,crop={TILE_W}:{TILE_H}",
         str(out)])
    return out


def contact_sheet(shot_id, query, cands, out_path, tmp):
    cols = 3
    rows = max(1, (len(cands) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * TILE_W, rows * TILE_H + 40), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    d.text((8, 8), f"{shot_id}: {query}", fill=(255, 220, 0), font=font)
    for i, c in enumerate(cands):
        x, y = (i % cols) * TILE_W, 40 + (i // cols) * TILE_H
        try:
            sheet.paste(Image.open(frame_from(c["preview"], tmp)), (x, y))
        except Exception as e:
            log(f"preview failed {c['id']}: {e}")
        d.rectangle([x, y, x + 46, y + 30], fill=(0, 0, 0))
        d.text((x + 8, y + 3), str(i), fill=(255, 255, 255), font=font)
        d.text((x + 6, y + TILE_H - 28), f"{c['width']}x{c['height']} {c['duration']}s",
               fill=(255, 255, 255), font=font)
    sheet.save(out_path, quality=80)


def main(ep_id):
    ep = load_json(ROOT / "episodes" / f"{ep_id}.json")
    wd = episode_dir(ep_id)
    (wd / "sheets").mkdir(parents=True, exist_ok=True)

    text = " ".join(l["text"] for l in ep["lines"])
    mp3, wjson = wd / "voice.mp3", wd / "words.json"
    if not mp3.exists():
        voice.synthesize(text, mp3, wjson, voice_id=ep.get("voice_id", voice.DEFAULT_VOICE))
    words = load_json(wjson)["words"]
    spans = line_spans(ep["lines"], words)

    make_sfx()

    plan = {"lines": [], "candidates": {}}
    with tempfile.TemporaryDirectory() as tmp:
        for li, line in enumerate(ep["lines"]):
            plan["lines"].append({"text": line["text"], "words": list(spans[li]),
                                  "shots": [f"L{li}S{si}" for si in range(len(line["shots"]))]})
            for si, query in enumerate(line["shots"]):
                sid = f"L{li}S{si}"
                cands = footage.search(query)
                plan["candidates"][sid] = {"query": query, "items": cands}
                log(f"{sid} '{query}': {len(cands)} candidates")
                if cands:
                    contact_sheet(sid, query, cands, wd / "sheets" / f"{sid}.jpg", tmp)
    save_json(wd / "plan.json", plan)
    log("fetch stage done")


if __name__ == "__main__":
    main(sys.argv[1])
