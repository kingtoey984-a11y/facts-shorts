"""Stock footage search (Pixabay now, Pexels when a key is added)."""
import json

from common import http, env, log, q


def search_pixabay(query, n=8):
    key = env("PIXABAY_API_KEY")
    url = (f"https://pixabay.com/api/videos/?key={key}&q={q(query)}&per_page={max(n, 3)}"
           f"&safesearch=true&order=popular")
    try:
        hits = json.loads(http(url))["hits"]
    except Exception as e:
        log(f"pixabay search failed for '{query}': {e}")
        return []
    out = []
    for h in hits:
        v = h["videos"]
        best = next((v[k] for k in ("large", "medium", "small") if v.get(k, {}).get("url")), None)
        preview = next((v[k] for k in ("tiny", "small", "medium") if v.get(k, {}).get("url")), None)
        if not best or not preview:
            continue
        if best["width"] < 960 and best["height"] < 960:
            continue
        out.append({
            "source": "pixabay", "id": h["id"], "page": h.get("pageURL", ""),
            "tags": h.get("tags", ""), "duration": h.get("duration", 0),
            "url": best["url"], "width": best["width"], "height": best["height"],
            "preview": preview["url"], "thumb": best.get("thumbnail") or preview.get("thumbnail", ""),
        })
    return out[:n]


def search_pexels(query, n=8):
    key = env("PEXELS_API_KEY", required=False)
    if not key:
        return []
    url = f"https://api.pexels.com/videos/search?query={q(query)}&per_page={n}&orientation=portrait"
    try:
        vids = json.loads(http(url, headers={"Authorization": key}))["videos"]
    except Exception as e:
        log(f"pexels search failed for '{query}': {e}")
        return []
    out = []
    for vd in vids:
        files = sorted([f for f in vd["video_files"] if f.get("width")],
                       key=lambda f: f["width"] * f["height"])
        if not files:
            continue
        best = next((f for f in files if f["height"] >= 1920), files[-1])
        out.append({
            "source": "pexels", "id": vd["id"], "page": vd.get("url", ""), "tags": "",
            "duration": vd.get("duration", 0), "url": best["link"], "width": best["width"],
            "height": best["height"], "preview": files[0]["link"], "thumb": vd.get("image", ""),
        })
    return out


def search(query, n=6):
    """Mix sources, prefer tall/vertical and longer clips, de-duplicate."""
    found = search_pexels(query, n) + search_pixabay(query, n + 2)
    seen, uniq = set(), []
    for c in found:
        k = (c["source"], c["id"])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    uniq.sort(key=lambda c: (c["height"] >= c["width"], min(c["duration"], 12)), reverse=True)
    return uniq[:n]
