"""Make short narration samples so the owner can pick the channel voice.

usage: python factory/voice_samples.py
"""
import json

from common import ROOT, http, env, log

API = "https://api.elevenlabs.io/v1"
TEXT = "Every night, your body paralyzes you... and that's not even the weirdest part."
CANDIDATES = [  # premade ElevenLabs voices; skipped if not available on the account
    ("A_Liam_energetic", "TX3LPaxmHKxFdv7VOQHJ"),
    ("B_Chris_casual", "iP95p4xoKVk53GoZ742B"),
    ("C_Jessica_expressive", "cgSgspJ2msm6clMCkdW9"),
    ("D_Will_friendly", "bIHbv24MWmeRgasZH58o"),
]
SETTINGS = {"stability": 0.32, "similarity_boost": 0.8, "style": 0.6,
            "use_speaker_boost": True, "speed": 1.08}


def main():
    hdr = {"xi-api-key": env("ELEVENLABS_API_KEY")}
    try:
        have = {v["voice_id"] for v in json.loads(http(f"{API}/voices", headers=hdr))["voices"]}
    except Exception:
        have = None
    out = ROOT / "samples"
    out.mkdir(exist_ok=True)
    made = 0
    for name, vid in CANDIDATES:
        if made == 3:
            break
        if have is not None and vid not in have:
            log(f"skip {name}: not on account")
            continue
        try:
            audio = http(f"{API}/text-to-speech/{vid}?output_format=mp3_44100_192",
                         data={"text": TEXT, "model_id": "eleven_multilingual_v2",
                               "voice_settings": SETTINGS},
                         headers=hdr, method="POST")
            (out / f"voice_{name}.mp3").write_bytes(audio)
            made += 1
            log(f"sample: {name}")
        except Exception as e:
            log(f"::warning::{name} failed: {e}")


if __name__ == "__main__":
    main()
