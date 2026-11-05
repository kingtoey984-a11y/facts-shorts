"""Ranking montage format (no narration): countdown board, ~5 s per item, music-driven.

usage: python factory/montage.py ep003 [--fetch] [--preview]
  --fetch   search footage candidates + contact sheets (+ music)
  default   render the clip from picks.json
"""
import sys
import tempfile

import fetch
import footage
import hud
import render
from common import ROOT, die, download, episode_dir, load_json, log, run, save_json, probe_duration

NATURAL = "eq=contrast=1.08:saturation=1.22:gamma=0.98,unsharp=5:5:0.6,vignette=PI/6,format=yuv420p"


def do_fetch(ep):
    wd = episode_dir(ep["id"])
    (wd / "sheets").mkdir(parents=True, exist_ok=True)
    plan = {"lines": [], "candidates": {}}
    with tempfile.TemporaryDirectory() as tmp:
        for li, it in enumerate(ep["items"]):
            ids = [f"L{li}S{si}" for si in range(len(it["shots"]))]
            plan["lines"].append({"label": it["label"], "dur": it.get("dur", 5.0), "shots": ids})
            for sid, query in zip(ids, it["shots"]):
                cands = footage.search(query, n=9)
                plan["candidates"][sid] = {"query": query, "items": cands}
                log(f"{sid} '{query}': {len(cands)}")
                if cands:
                    fetch.contact_sheet(sid, query, cands, wd / "sheets" / f"{sid}.jpg", tmp)
    save_json(wd / "plan.json", plan)
    get_music(ep)


def get_music(ep):
    mdir = ROOT / "assets" / "music"
    credits_file = mdir / "credits.json"
    credits = load_json(credits_file) if credits_file.exists() else {}
    for title in ep.get("music", []):
        name = title.replace(" ", "_") + ".mp3"
        url = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/" + title.replace(" ", "%20") + ".mp3"
        try:
            download(url, mdir / name)
            credits[name] = (f'Music: "{title}" by Kevin MacLeod (incompetech.com), '
                             "licensed under Creative Commons: By Attribution 4.0")
            log(f"music ready: {title}")
        except Exception as e:
            log(f"::warning::music {title} unavailable ({e})")
            (mdir / name).unlink(missing_ok=True)
    save_json(credits_file, credits)


def timeline(plan):
    shots, t = [], 0.0
    starts = []
    for li, line in enumerate(plan["lines"]):
        starts.append(t)
        step = line["dur"] / len(line["shots"])
        for k, sid in enumerate(line["shots"]):
            shots.append({"id": sid, "line": li, "start": t + k * step, "dur": step, "punch": k == 0})
        t += line["dur"]
    return t, starts, shots


def render_shot(s, idx, cache, out, base_png):
    c = s["clip"]
    src = download(c["url"], cache / f"{c['source']}_{c['id']}.mp4")
    clip_len = probe_duration(src)
    need = s["dur"] + 0.1
    ss = s["ss"] if s["ss"] is not None else min(0.5, max(0.0, clip_len - need))
    ss = max(0.0, min(ss, max(0.0, clip_len - need)))
    frames = max(1, round(s["dur"] * 30))
    z = (f"if(lt(on,6),1.18-0.03*on,1.0+0.06*(on-6)/{frames})" if s["punch"]
         else f"1.06-0.06*on/{frames}")
    fc = (f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          f"scale=2160:3840,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":d=1:s=1080x1920:fps=30,setsar=1,{NATURAL}[g];"
          f"[1:v]format=rgba[b];[g][b]overlay=0:0:shortest=1[v]")
    loop = ["-stream_loop", "-1"] if clip_len < need else []
    run(["ffmpeg", "-y", "-v", "error", *loop, "-ss", f"{ss:.2f}", "-i", str(src),
         "-loop", "1", "-framerate", "30", "-i", str(base_png), "-filter_complex", fc,
         "-map", "[v]", "-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30", str(out)])


def build_audio(ep, total, starts, out):
    mdir = ROOT / "assets" / "music"
    track = mdir / ep["music_track"]
    if not track.exists():
        die(f"music {track.name} missing")
    sfx = ROOT / "assets" / "sfx"
    inputs = ["-stream_loop", "-1", "-i", str(track)]
    filt = [f"[0:a]aresample=48000,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume=0.9[m]"]
    mix = ["[m]"]
    cues = [("whoosh.mp3", max(0.0, t - 0.15), 0.55) for t in starts[1:]]
    cues.append(("hit.mp3", starts[-1], 0.8))
    n = 1
    for name, at, vol in cues:
        f = sfx / name
        if not f.exists():
            continue
        ms = int(at * 1000)
        inputs += ["-i", str(f)]
        filt.append(f"[{n}:a]aresample=48000,volume={vol},adelay={ms}|{ms}[s{n}]")
        mix.append(f"[s{n}]")
        n += 1
    filt.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first,"
                f"loudnorm=I={ep.get('lufs', -9)}:TP=-1.0:LRA=7,atrim=0:{total:.3f}[a]")
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filt),
         "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])


def do_render(ep, preview=False):
    wd = episode_dir(ep["id"])
    plan = load_json(wd / "plan.json")
    picks = load_json(wd / "picks.json") if (wd / "picks.json").exists() else {}
    total, starts, shots = timeline(plan)
    render.choose(plan, picks, shots)
    build, cache = wd / "_build", wd / "_cache"
    build.mkdir(exist_ok=True)
    items = [(len(ep["items"]) - i, it["label"]) for i, it in enumerate(ep["items"])]
    listing = []
    pv = wd / "preview"
    pv.mkdir(exist_ok=True)
    for i, s in enumerate(shots):
        base_png = build / f"{s['id']}_board.png"
        hud.ranking_layer(ep["board_title"], items, s["line"], numbers_hot=True).save(base_png)
        out = build / f"shot{i:02d}.mp4"
        render_shot(s, i, cache, out, base_png)
        listing.append(f"file '{out.name}'")
        if preview:
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{s['dur'] * 0.6:.2f}", "-i", str(out),
                 "-frames:v", "1", "-vf", "scale=540:960", str(pv / f"{s['id']}.jpg")])
    if preview:
        return
    (build / "list.txt").write_text("\n".join(listing))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(build / "list.txt"),
         "-c", "copy", str(build / "video.mp4")])
    build_audio(ep, total, starts, build / "audio.m4a")
    out_dir = ROOT / "clips"
    out_dir.mkdir(exist_ok=True)
    final = out_dir / f"{ep['id']}.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(build / "video.mp4"), "-i", str(build / "audio.m4a"),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy", "-t", f"{total:.3f}",
         "-movflags", "+faststart", str(final)])
    lufs = render.measure_lufs(final)
    credit = load_json(ROOT / "assets" / "music" / "credits.json").get(ep["music_track"], "")
    qc = {"duration": round(probe_duration(final), 2), "lufs": lufs, "shots": len(shots),
          "music": ep["music_track"],
          "footage": [{"shot": s["id"], "page": s["clip"]["page"]} for s in shots]}
    save_json(out_dir / f"{ep['id']}.qc.json", qc)
    (out_dir / f"{ep['id']}.post.txt").write_text(
        f"TITLE:\n{ep['title']}\n\nDESCRIPTION:\n{ep['description']}\n\n"
        f"{' '.join(ep['hashtags'])}\n\n{credit}\n", encoding="utf-8")
    log(f"QC {qc['duration']}s {lufs} LUFS")


if __name__ == "__main__":
    ep = load_json(ROOT / "episodes" / f"{sys.argv[1]}.json")
    if "--fetch" in sys.argv:
        do_fetch(ep)
    else:
        do_render(ep, preview="--preview" in sys.argv)
