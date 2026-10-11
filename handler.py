"""Runpod serverless worker: style text + lyrics → one YuE2 song (MP3, base64).

Input (job["input"]):
    style         str, required   the style description; short and structured works best (see styles.json)
    lyrics        str, required   Suno-style lyrics are fine; tags are normalised and production notes dropped
    clean_lyrics  bool  = true    false sends the lyrics untouched
    seed          int   = random
    cfg_scale     float = model default (1.0)
    semantic_sampling, abc_sampling   dict, optional overrides of YuE2's sampling for the audio-token and the
                  score (ABC) stage: temperature, top_p, top_k, repetition_penalty. Defaults: semantic T 1.0,
                  top_p 0.95, top_k 100, rp 1.2; abc T 0.7, top_p 0.9, top_k 30, rp 1.005
    ode_steps     int   = 64      audio synthesis steps (1-128); YuE2's own default is 32. 64 costs ~2 s more; by ear
                  32/64/128 sound alike, 64 kept as a margin
    bitrate       str   = "192k"  lowered automatically if the MP3 would not fit in a job response

Output: {audio_base64, format, seconds, gen_seconds, seed, cfg_scale, *_sampling, truncated, lyrics_sent, style_chars,
        weights, gpu}
One take per job; for several takes send several jobs (they run on parallel workers up to the endpoint's max).

Local test on a GPU box:  python handler.py --test_input "$(cat test_input.json)"
"""
from __future__ import annotations

import base64
import dataclasses
import os
import random
import subprocess
import tempfile
import time
from pathlib import Path

import runpod
import soundfile as sf
import torch
from yue2 import YuE2Pipeline

from lyrics import to_yue2

MODEL_REPO = "m-a-p/YuE2-3B"
MODEL_REV = "8f24312f187763b9854adeec87e437e2b03bbff1"  # the revision the bake-off was judged on
VAE_DIR = os.environ.get("YUE2_VAE_DIR", "/models/YuE2-Vae")  # baked into the image
RUNPOD_CACHE = Path(os.environ.get("RUNPOD_HF_CACHE", "/runpod-volume/huggingface-cache/hub"))
MAX_B64 = 9_000_000  # /run results cap at ~10 MB
BITRATES = ["192k", "160k", "128k", "96k"]
ODE_STEPS = 64
SAMPLING_KEYS = {"temperature": float, "top_p": float, "top_k": int, "repetition_penalty": float}


def model_source() -> tuple[str, str]:
    """The endpoint's cached model (Runpod --model-reference) if present, else download from the Hub."""
    snaps = RUNPOD_CACHE / "models--m-a-p--YuE2-3B" / "snapshots"
    if (snaps / MODEL_REV).is_dir():
        return str(snaps / MODEL_REV), "runpod-cache"
    if snaps.is_dir() and any(snaps.iterdir()):
        return str(sorted(snaps.iterdir())[-1]), "runpod-cache (other revision)"
    return MODEL_REPO, "hub-download"


t0 = time.time()
SRC, HOW = model_source()
print(f"loading {SRC} ({HOW}), vae {VAE_DIR}", flush=True)
PIPE = YuE2Pipeline.from_pretrained(SRC, vae=VAE_DIR, revision=MODEL_REV if HOW == "hub-download" else None,
                                    device="cuda", progress=False)
GPU = torch.cuda.get_device_name(0)
DEFAULT_CONFIG = PIPE.generation_config
print(f"ready in {time.time() - t0:.1f}s on {GPU}", flush=True)


def to_mp3(flac: Path, bitrate: str) -> bytes:
    out = flac.with_suffix(f".{bitrate}.mp3")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(flac), "-b:a", bitrate, str(out)], check=True)
    return out.read_bytes()


def handler(job):
    inp = job["input"]
    style, lyrics = str(inp.get("style") or "").strip(), str(inp.get("lyrics") or "").strip()
    if not style or not lyrics:
        return {"error": "style and lyrics are both required"}
    if len(style) > 2000:
        return {"error": f"style is {len(style)} chars; keep it under 2000 (about 250 works best)"}
    sent = to_yue2(lyrics) if inp.get("clean_lyrics", True) else lyrics
    seed = int(inp["seed"]) if inp.get("seed") is not None else random.randrange(2**31)
    kw = {"id": f"job-{str(job.get('id', 'local'))[:12]}", "style": style, "lyrics": sent, "cot": "full", "seed": seed}
    if inp.get("cfg_scale") is not None:
        kw["cfg_scale"] = float(inp["cfg_scale"])
    for stage in ("semantic_sampling", "abc_sampling"):
        if inp.get(stage):
            bad = set(inp[stage]) - set(SAMPLING_KEYS)
            if bad:
                return {"error": f"{stage}: unknown keys {sorted(bad)}; allowed {sorted(SAMPLING_KEYS)}"}
            kw[stage] = {k: SAMPLING_KEYS[k](v) for k, v in inp[stage].items()}

    steps = int(inp.get("ode_steps") or ODE_STEPS)
    if not 1 <= steps <= 128:
        return {"error": "ode_steps must be 1-128"}

    t = time.time()
    PIPE.generation_config = dataclasses.replace(DEFAULT_CONFIG, ode_steps=steps)  # one job per worker at a time
    try:
        song = PIPE(**kw)
    except ValueError as e:  # bad sampling values etc.
        return {"error": f"invalid settings: {e}"}
    finally:
        PIPE.generation_config = DEFAULT_CONFIG
    gen = time.time() - t
    with tempfile.TemporaryDirectory() as d:
        flac = Path(d) / "song.flac"
        song.save(flac)
        seconds = sf.info(str(flac)).duration
        rates = BITRATES[BITRATES.index(inp["bitrate"]):] if inp.get("bitrate") in BITRATES else BITRATES
        for rate in rates:
            b64 = base64.b64encode(to_mp3(flac, rate)).decode()
            if len(b64) <= MAX_B64:
                break
        else:
            return {"error": f"{seconds:.0f} s song does not fit in a job response even at {rate}"}
    return {"audio_base64": b64, "format": "mp3", "bitrate": rate, "seconds": round(seconds, 1),
            "gen_seconds": round(gen, 1), "seed": seed, "cfg_scale": kw.get("cfg_scale", 1.0), "ode_steps": steps,
            "semantic_sampling": kw.get("semantic_sampling"), "abc_sampling": kw.get("abc_sampling"), "truncated": song.truncated, "lyrics_sent": sent,
            "style_chars": len(style), "weights": f"{SRC.split('/')[-1][:12]} ({HOW})", "gpu": GPU}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
