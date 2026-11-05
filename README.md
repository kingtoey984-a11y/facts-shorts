# facts-shorts

Automated English facts Shorts factory.

- `episodes/<id>.json` – script lines + a shot query per beat
- `factory/fetch.py` – ElevenLabs narration (word timestamps), Pixabay/Pexels candidates, contact sheets for review
- `factory/render.py` – cuts every ~2 s with slow zooms, word-pop captions, SFX, optional music (`assets/music/*.mp3`), -14 LUFS, QC
- `jobs/next.json` – push a change here (or run the workflow by hand) to produce
- Output: `clips/<id>.mp4` + `<id>.post.txt` (title/description/hashtags) + `<id>.qc.json`

Secrets: `ELEVENLABS_API_KEY`, `PIXABAY_API_KEY`, optional `PEXELS_API_KEY`.
