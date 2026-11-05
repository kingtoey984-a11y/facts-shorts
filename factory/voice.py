"""Narration via ElevenLabs text-to-speech with character timestamps -> word timings."""
import base64
import re

from common import http, env, log, die, save_json

API = "https://api.elevenlabs.io/v1"
# Brian: deep, warm American male narrator. Falls back to any premade American male voice.
DEFAULT_VOICE = "nPczCjzI2devNBz1zQrb"
MODEL = "eleven_multilingual_v2"


def _headers():
    return {"xi-api-key": env("ELEVENLABS_API_KEY")}


def credits_left():
    try:
        import json
        sub = json.loads(http(f"{API}/user/subscription", headers=_headers()))
        return sub["character_limit"] - sub["character_count"]
    except Exception as e:  # permission may be off; not fatal
        log(f"could not read credits: {e}")
        return None


def pick_voice(preferred):
    import json
    try:
        voices = json.loads(http(f"{API}/voices", headers=_headers()))["voices"]
    except Exception as e:
        log(f"voice list unavailable ({e}); using {preferred}")
        return preferred
    ids = {v["voice_id"] for v in voices}
    if preferred in ids:
        return preferred
    for v in voices:
        lab = v.get("labels") or {}
        if lab.get("gender") == "male" and "american" in (lab.get("accent") or "").lower():
            log(f"preferred voice missing; using {v['name']}")
            return v["voice_id"]
    return voices[0]["voice_id"]


def synthesize(text, out_mp3, out_words, voice_id=DEFAULT_VOICE, speed=1.05):
    left = credits_left()
    if left is not None:
        log(f"ElevenLabs credits left: {left}")
        if left < len(text) * 2:
            die(f"ElevenLabs credits too low ({left}). Top up before producing more clips.")
    voice_id = pick_voice(voice_id)
    import json
    payload = {
        "text": text,
        "model_id": MODEL,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8,
                           "style": 0.35, "use_speaker_boost": True, "speed": speed},
    }
    raw = http(f"{API}/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_192",
               data=payload, headers=_headers(), method="POST", timeout=300)
    res = json.loads(raw)
    out_mp3.write_bytes(base64.b64decode(res["audio_base64"]))
    al = res.get("normalized_alignment") or res["alignment"]
    words = chars_to_words(al["characters"], al["character_start_times_seconds"],
                           al["character_end_times_seconds"])
    save_json(out_words, {"voice_id": voice_id, "text": text, "words": words})
    log(f"narration: {len(words)} words, {words[-1]['end']:.2f}s")
    return words


def chars_to_words(chars, starts, ends):
    words, cur, s, e = [], "", None, None
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({"w": cur, "start": s, "end": e})
            cur, s = "", None
            continue
        if s is None:
            s = st
        cur += ch
        e = en
    if cur:
        words.append({"w": cur, "start": s, "end": e})
    return words


def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())
