"""Stage 2: cut footage to the narration, word-pop captions, sound, loudness, QC.

usage: python factory/render.py ep001
"""
import hashlib
import os
import re
import sys
from pathlib import Path

import hud
from common import (FPS, H, ROOT, W, die, download, episode_dir, load_json, log,
                    probe_duration, run, save_json)

FONT = os.environ.get("CAPTION_FONT", "Anton")
FONT_DIR = ROOT / "assets" / "fonts"
YELLOW = "&H000AD6FF&"
WHITE = "&H00FFFFFF&"
NUMBERS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"}
MIN_SHOT = 1.3
CAPTION_Y = 1180  # ~60% down: clear of the Shorts title/buttons area


# ---------- timeline ----------
def build_timeline(plan, words):
    t0 = max(0.0, words[0]["start"] - 0.03)          # trim leading silence for a tight loop
    for w in words:
        w["start"] -= t0
        w["end"] -= t0
    total = words[-1]["end"] + 0.12
    lines = plan["lines"]
    starts = [0.0] + [words[l["words"][0]]["start"] for l in lines[1:]]
    ends = starts[1:] + [total]
    shots = []
    for li, l in enumerate(lines):
        length = ends[li] - starts[li]
        ids = l["shots"][:max(1, int(length // MIN_SHOT))]
        step = length / len(ids)
        for k, sid in enumerate(ids):
            shots.append({"id": sid, "line": li, "start": starts[li] + k * step, "dur": step,
                          "punch": k == 0})
    return t0, total, starts, shots


# ---------- footage ----------
def choose(plan, picks, shots):
    used = set()
    for s in shots:
        pick = picks.get(s["id"], 0)
        if isinstance(pick, int):
            pick = {"i": pick}
        # "from" lets a reviewer borrow a better candidate found under another shot's search
        items = plan["candidates"].get(pick.get("from", s["id"]), {}).get("items", [])
        idx, ss = pick.get("i", 0), pick.get("ss")
        order = [idx] + [i for i in range(len(items)) if i != idx]
        chosen = next((items[i] for i in order if i < len(items)
                       and (items[i]["source"], items[i]["id"]) not in used), None)
        if not chosen:
            # borrow any unused clip from the same line
            for other in plan["candidates"].values():
                chosen = next((c for c in other["items"] if (c["source"], c["id"]) not in used), None)
                if chosen:
                    break
        if not chosen:
            die(f"no footage for {s['id']}")
        used.add((chosen["source"], chosen["id"]))
        s["clip"], s["ss"] = chosen, ss


def make_overlays(ep, s, build):
    """Static DNA layer (brackets, scanlines, file tag) + optional animated callout layer."""
    line = ep["lines"][s["line"]]
    tag_text = f"FILE {ep['id'][-2:]} // {line.get('tag', ep.get('tag', 'UNSEEN'))}"
    base = hud.overlay({"tag": tag_text})
    base_png = build / f"{s['id']}_base.png"
    base.save(base_png)
    spec = (ep.get("hud") or {}).get(s["id"])
    if not spec:
        return base_png, None
    from PIL import Image
    callout = hud.overlay_parts(spec)
    call_png = build / f"{s['id']}_call.png"
    callout.save(call_png)
    return base_png, call_png


def render_shot(s, idx, cache, out, base_png, call_png):
    c = s["clip"]
    src = download(c["url"], cache / f"{c['source']}_{c['id']}.mp4")
    clip_len = probe_duration(src)
    need = s["dur"] + 0.1
    ss = s["ss"] if s["ss"] is not None else min(0.4, max(0.0, clip_len - need))
    ss = max(0.0, min(ss, max(0.0, clip_len - need)))
    frames = max(1, round(s["dur"] * FPS))
    if s.get("punch"):
        z = f"if(lt(on,6),1.22-0.037*on,1.0+0.08*(on-6)/{frames})"
    elif idx % 2 == 0:
        z = f"1+0.10*on/{frames}"
    else:
        z = f"1.10-0.10*on/{frames}"
    fc = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"scale={W*2}:{H*2},"
          f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
          f"setsar=1,{hud.GRADE}[g];"
          f"[1:v]format=rgba[b];[g][b]overlay=0:0:shortest=1[gb]")
    inputs = ["-loop", "1", "-framerate", str(FPS), "-i", str(base_png)]
    last = "gb"
    if call_png:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(call_png)]
        fc += (f";[2:v]format=rgba,fade=in:st=0.12:d=0.22:alpha=1[c];"
               f"[gb][c]overlay=0:0:shortest=1[gc]")
        last = "gc"
    loop = ["-stream_loop", "-1"] if clip_len < need else []
    run(["ffmpeg", "-y", "-v", "error", *loop, "-ss", f"{ss:.2f}", "-i", str(src), *inputs,
         "-filter_complex", fc, "-map", f"[{last}]", "-frames:v", str(frames), "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-r", str(FPS), str(out)])


# ---------- captions ----------
def ass_time(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def clean(w):
    w = w.upper().replace("—", "")
    return re.sub(r"[.,;:]+$", "", w)


def chunk_words(words):
    chunks, cur = [], []
    for w in words:
        bare = re.sub(r"[^a-z]", "", w["w"].lower())
        if bare in NUMBERS and w["w"].endswith(":"):
            if cur:
                chunks.append(cur)
            chunks.append([dict(w, big=True)])
            cur = []
            continue
        cur.append(w)
        chars = sum(len(x["w"]) for x in cur)
        if len(cur) >= 3 or chars >= 14 or re.search(r"[.,:?!—]$", w["w"]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def write_ass(words, total, path):
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT},118,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,7,4,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    chunks = chunk_words(words)
    for ci, ch in enumerate(chunks):
        c_end = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else total
        for k, w in enumerate(ch):
            st = ch[0]["start"] if k == 0 else w["start"]
            en = ch[k + 1]["start"] if k + 1 < len(ch) else c_end
            if en <= st:
                continue
            parts = []
            for j, x in enumerate(ch):
                col = YELLOW if j == k else WHITE
                parts.append(f"{{\\c{col}}}{clean(x['w'])}")
            tag = f"\\an5\\pos({W // 2},{CAPTION_Y})"
            if w.get("big"):
                tag += f"\\fs190\\c{YELLOW}"
            if k == 0:
                tag += "\\fscx72\\fscy72\\t(0,90,\\fscx108\\fscy108)\\t(90,160,\\fscx100\\fscy100)"
            events.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Cap,,0,0,0,,{{{tag}}}"
                          + " ".join(parts))
    Path(path).write_text(head + "\n".join(events) + "\n", encoding="utf-8")


# ---------- audio ----------
def build_audio(wd, t0, total, line_starts, out):
    voice = wd / "voice.mp3"
    inputs = ["-ss", f"{t0:.3f}", "-t", f"{total:.3f}", "-i", str(voice)]
    filters = ["[0:a]aresample=48000,volume=1.0[v]"]
    mix = ["[v]"]
    n = 1
    sfx = ROOT / "assets" / "sfx"
    cues = [("whoosh.mp3", max(0.0, t - 0.18), 0.32) for t in line_starts[1:]]
    cues.append(("hit.mp3", 0.0, 0.30))
    for name, at, vol in cues:
        f = sfx / name
        if not f.exists():
            continue
        inputs += ["-i", str(f)]
        ms = int(at * 1000)
        filters.append(f"[{n}:a]aresample=48000,volume={vol},adelay={ms}|{ms}[s{n}]")
        mix.append(f"[s{n}]")
        n += 1
    music = sorted((ROOT / "assets" / "music").glob("*.mp3"))
    if music:
        track = music[int(hashlib.md5(wd.name.encode()).hexdigest(), 16) % len(music)]
        build_audio.track = track.name
        inputs += ["-stream_loop", "-1", "-i", str(track)]
        filters.append(f"[{n}:a]aresample=48000,volume=0.16,atrim=0:{total:.3f}[m]")
        filters.append("[m][v]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[md]")
        # sidechain consumes [v]; re-split voice first
        filters[0] = "[0:a]aresample=48000,asplit=2[v][vk]"
        filters[-1] = "[m][vk]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[md]"
        mix.append("[md]")
        n += 1
    filters.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,"
                   f"loudnorm=I=-14:TP=-1.5:LRA=11,atrim=0:{total:.3f}[a]")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters),
         "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])


def measure_lufs(path):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"])
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
    return float(m[-1]) if m else None


# ---------- main ----------
def main(ep_id, preview=False):
    ep = load_json(ROOT / "episodes" / f"{ep_id}.json")
    wd = episode_dir(ep_id)
    plan = load_json(wd / "plan.json")
    words = load_json(wd / "words.json")["words"]
    picks_file = wd / "picks.json"
    picks = load_json(picks_file) if picks_file.exists() else {}
    t0, total, line_starts, shots = build_timeline(plan, words)
    choose(plan, picks, shots)
    log(f"timeline {total:.2f}s, {len(shots)} shots")

    build = wd / "_build"
    cache = wd / "_cache"
    build.mkdir(exist_ok=True)
    listing = []
    pv = wd / "preview"
    if preview:
        pv.mkdir(exist_ok=True)
    for i, s in enumerate(shots):
        out = build / f"shot{i:02d}.mp4"
        base_png, call_png = make_overlays(ep, s, build)
        render_shot(s, i, cache, out, base_png, call_png)
        listing.append(f"file '{out.name}'")
        if preview:
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s['dur'] * 0.6:.2f}", "-i", str(out),
                 "-frames:v", "1", "-vf", "scale=540:960", str(pv / f"{s['id']}.jpg")])
    if preview:
        log("preview frames written")
        return
    (build / "list.txt").write_text("\n".join(listing))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(build / "list.txt"),
         "-c", "copy", str(build / "video.mp4")])

    write_ass(words, total, build / "captions.ass")
    build_audio(wd, t0, total, line_starts, build / "audio.m4a")

    out_dir = ROOT / "clips"
    out_dir.mkdir(exist_ok=True)
    final = out_dir / f"{ep_id}.mp4"
    ass = str(build / "captions.ass").replace(":", r"\:")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(build / "video.mp4"), "-i", str(build / "audio.m4a"),
         "-vf", f"ass={ass}:fontsdir={FONT_DIR}", "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-t", f"{total:.3f}", "-movflags", "+faststart", str(final)])

    # ---- QC ----
    dur = probe_duration(final)
    lufs = measure_lufs(final)
    qc = {"duration": round(dur, 2), "lufs": lufs, "shots": len(shots),
          "avg_shot": round(total / len(shots), 2),
          "ok_duration": dur <= 59.5, "ok_loudness": lufs is not None and -16 <= lufs <= -12,
          "footage": [{"shot": s["id"], "source": s["clip"]["source"], "page": s["clip"]["page"]}
                      for s in shots]}
    credit = ""
    track = getattr(build_audio, "track", None)
    cfile = ROOT / "assets" / "music" / "credits.json"
    if track and cfile.exists():
        credit = load_json(cfile).get(track, "")
    post = (f"TITLE:\n{ep['title']}\n\nDESCRIPTION:\n{ep['description']}\n\n"
            f"{' '.join(ep['hashtags'])}\n" + (f"\n{credit}\n" if credit else ""))
    qc["music"] = track
    save_json(out_dir / f"{ep_id}.qc.json", qc)
    (out_dir / f"{ep_id}.post.txt").write_text(post, encoding="utf-8")
    log(f"QC: {qc['duration']}s, {lufs} LUFS, {len(shots)} shots")
    if not (qc["ok_duration"] and qc["ok_loudness"]):
        die(f"QC failed: {qc}")


if __name__ == "__main__":
    main(sys.argv[1], preview="--preview" in sys.argv)
