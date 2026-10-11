"""Make songs on the Runpod endpoint. Standard library only.

    python client/ltbr_song.py --style up-and-out --lyrics client/example_lyrics.txt
    python client/ltbr_song.py --style "English, 1980s lovers rock, ..." --lyrics my.txt --seed 7 --takes 4

--style is a preset name from styles.json or the style text itself. Like Suno, one request gives 2 takes by
default, each with different settings from TAKE_PLAN (more takes cycle through it with new seeds). Each take is
its own job, so takes run in parallel on as many workers as the endpoint allows. Songs land in out/ as
<time>-<style>-<take>-<seed>.mp3 + .json (the .json records every setting, so a take can be re-made exactly).

Needs RUNPOD_API_KEY and LTBR_ENDPOINT_ID, from the environment or a .env file in the project root.
"""
from __future__ import annotations

import argparse
import base64
import functools
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLES = json.loads((ROOT / "styles.json").read_text())
OUT = ROOT / "out"

# One request = these takes. A is the bake-off's most reliable setting; B varies it the way that won on some songs
# (Up and Out, Concrete Weather) though not on average. Change B here to explore other directions; the handler
# also takes semantic_sampling / abc_sampling dicts (temperature, top_p, top_k, repetition_penalty).
TAKE_PLAN = [
    {"take": "A", "note": "model defaults (guidance 1.0)"},
    {"take": "B", "note": "stronger style guidance (1.2)", "cfg_scale": 1.2},
]


def config() -> tuple[str, str]:
    env = dict(os.environ)
    if (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() and not line.lstrip().startswith("#"):
                env.setdefault(k.strip(), v.strip().strip('"'))
    key, ep = env.get("RUNPOD_API_KEY"), env.get("LTBR_ENDPOINT_ID")
    if not key or not ep:
        sys.exit("set RUNPOD_API_KEY and LTBR_ENDPOINT_ID (environment or .env)")
    return key, ep


def api(method: str, path: str, body: dict | None = None) -> dict:
    key, ep = config()
    req = urllib.request.Request(f"https://api.runpod.ai/v2/{ep}/{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def resolve_style(style: str) -> tuple[str, str]:
    """(name for file names, style text)."""
    if style in STYLES:
        return style, STYLES[style]["style"]
    return next((k for k, v in STYLES.items() if v["style"] == style.strip()), "custom"), style


def submit(style: str, lyrics: str, seed: int, settings: dict, clean_lyrics: bool = True) -> str:
    inp = {"style": style, "lyrics": lyrics, "clean_lyrics": clean_lyrics, "seed": seed}
    inp |= {k: v for k, v in settings.items() if k in ("cfg_scale", "semantic_sampling", "abc_sampling", "ode_steps")}
    return api("POST", "run", {"input": inp})["id"]


def wait(job_id: str, on_status=None, poll: float = 5, timeout: float = 1800) -> dict:
    """Poll until the job ends. Returns the /status body (status COMPLETED → output holds the song)."""
    t0 = time.time()
    while True:
        try:
            s = api("GET", f"status/{job_id}")
        except (urllib.error.URLError, TimeoutError) as e:  # transient; keep polling
            s = {"status": f"poll error: {e}"}
        if on_status:
            on_status(s.get("status"))
        if s.get("status") in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            return s
        if time.time() - t0 > timeout:
            api("POST", f"cancel/{job_id}")
            return {"status": "TIMED_OUT", "id": job_id}
        time.sleep(poll)


def save(result: dict, name: str, style: str, take: dict | None = None) -> Path | None:
    out = result.get("output") or {}
    if result.get("status") != "COMPLETED" or "audio_base64" not in out:
        return None
    OUT.mkdir(exist_ok=True)
    tag = f"-{take['take']}" if take else ""
    stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{re.sub(r'[^a-z0-9-]+', '-', name.lower())}{tag}-{out['seed']}"
    mp3 = OUT / f"{stem}.mp3"
    mp3.write_bytes(base64.b64decode(out.pop("audio_base64")))
    meta = {k: result.get(k) for k in ("id", "delayTime", "executionTime")} | (take or {}) | out | {"style": style}
    mp3.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    return mp3


def plan(takes: int, seed: int | None = None, cfg_scale: float | None = None) -> list[dict]:
    """Settings per take: TAKE_PLAN cycled, consecutive seeds; --cfg-scale pins guidance for every take."""
    base = seed if seed is not None else random.randrange(2**31 - 100)
    out = []
    for i in range(takes):
        t = dict(TAKE_PLAN[i % len(TAKE_PLAN)])
        if i >= len(TAKE_PLAN):
            t["take"] += str(i // len(TAKE_PLAN) + 1)
        if cfg_scale is not None:
            t |= {"cfg_scale": cfg_scale, "note": f"guidance {cfg_scale} (set by hand)"}
        out.append(t | {"seed": base + i})
    return out


def make(style: str, lyrics: str, takes: int = 2, seed: int | None = None, cfg_scale: float | None = None,
         clean_lyrics: bool = True, log=functools.partial(print, flush=True)) -> list[Path]:
    name, text = resolve_style(style)
    takes_ = plan(takes, seed, cfg_scale)
    ids = [submit(text, lyrics, t["seed"], t, clean_lyrics) for t in takes_]
    for t, i in zip(takes_, ids):
        log(f"take {t['take']} ({t['note']}, seed {t['seed']}): job {i}")
    by_id = dict(zip(ids, takes_))

    def one(job_id: str) -> Path | None:
        last = [None]

        def on(st):
            if st != last[0]:
                log(f"{job_id}: {st}")
                last[0] = st

        r = wait(job_id, on)
        p = save(r, name, text, by_id[job_id])
        if p:
            o = json.loads(p.with_suffix(".json").read_text())
            log(f"take {o['take']}: {o['seconds']} s of song, generated in {o['gen_seconds']} s, "
                f"queued {(r.get('delayTime') or 0) / 1000:.0f} s → {p}")
        else:
            log(f"{job_id}: {r.get('status')} {json.dumps(r.get('error') or r.get('output'))[:500]}")
        return p

    with ThreadPoolExecutor(len(ids)) as ex:
        return [p for p in ex.map(one, ids) if p]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--style", help="preset name or style text", required=False)
    ap.add_argument("--lyrics", help="lyrics file ('-' for stdin)")
    ap.add_argument("--takes", type=int, default=2, help="default 2: take A and B from TAKE_PLAN")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--cfg-scale", type=float, help="same guidance for every take (overrides TAKE_PLAN)")
    ap.add_argument("--raw-lyrics", action="store_true", help="send lyrics untouched")
    ap.add_argument("--list-styles", action="store_true")
    ap.add_argument("--health", action="store_true", help="show endpoint workers and queue")
    a = ap.parse_args()
    if a.list_styles:
        for k, v in STYLES.items():
            print(f"{k:24} {v['label']}\n{'':24} {v['style']}\n")
        return
    if a.health:
        print(json.dumps(api("GET", "health"), indent=1))
        return
    if not a.style or not a.lyrics:
        ap.error("--style and --lyrics are required")
    lyrics = sys.stdin.read() if a.lyrics == "-" else Path(a.lyrics).read_text()
    make(a.style, lyrics, a.takes, a.seed, a.cfg_scale, not a.raw_lyrics)


if __name__ == "__main__":
    main()
