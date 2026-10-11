# worker-yue2-3b

On-demand songs for LTBR.FM: a station style plus lyrics in, an MP3 out. It runs
[YuE2](https://github.com/multimodal-art-projection/YuE) on Runpod serverless, on an RTX 4090 with 24 GB.
There are no always-on workers, so it costs nothing when idle.

Background and the listening test behind every choice here are in `~/projects/yue-bakeoff`, especially
`docs/findings.md`. In short:
- **Style following:** YuE2 follows the genre of a catalogue style well.
- **Lyrics:** cleaning out Suno's production notes is the biggest win.
- **Style text:** a short structured style description beats the long Suno paragraph.
- **Seeds:** results vary a lot between seeds, so make 2–3 takes and pick one.
- **Speed:** about 80 s per 3.5-minute song once a worker is warm.

> **Licence:** YuE2's weights are CC BY-NC 4.0 with an "individual creator" permission. Settle whether LTBR.FM
> qualifies before anything made here is broadcast.

## What's here
| File | Role |
|---|---|
| `handler.py` | The serverless worker. It loads YuE2 once per worker, then makes one song per job and returns the MP3 as base64. The input fields are in the docstring. |
| `lyrics.py` | Suno-style lyrics → YuE2 section tags, with production notes dropped (from the bake-off). |
| `Dockerfile` | python 3.12 + torch 2.10 (CUDA 12.8) + YuE2 at the tested commit. The VAE (0.5 GB) is built into the image; the 7.3 GB main model comes from Runpod's model cache. |
| `styles.json` | Style presets. The 4 `simple` ones (keyboard man, busker ska, acoustic busker, jingle) are the default use: plain arrangements for disposable one-off tracks such as tube updates. The 8 `station` ones are the condensed prompts from the bake-off, each linked to its source track. Add more freely. |
| `client/example_short.txt`, `client/example_lyrics.txt` | Example lyrics: a short verse + chorus (30–60 s, about $0.01 a take) and a full tube update. |
| `client/ltbr_song.py` | Command-line client (standard library only). It sends N takes as N parallel jobs and saves them to `out/`. |
| `client/web.py` | A local page at http://localhost:8802: preset, style text, lyrics, takes → players. |
| `test_input.json` | A short sample job. |

## One-time setup
1. **GitHub:** push this folder to the repo. It can be private.
2. **Connect Runpod to GitHub:** Runpod console → Settings → Connections → GitHub → authorise, and give it
   access to this repo.
3. **Create the endpoint:** Runpod console → Serverless → New Endpoint → *GitHub Repo*, choose this repo, then:
   - Branch `main`, Dockerfile `Dockerfile`, build context `/`.
   - GPU: **24 GB, RTX 4090** (pool ADA_24). If the console offers a CUDA filter, set **12.8 or newer**.
   - Workers: **Active (min) 0**, **Max 2**. Idle timeout **30 s**. Execution timeout **900 s**.
   - Container disk **20 GB**.
   - **Model** (cached model): `https://huggingface.co/m-a-p/YuE2-3B`. Without it, every cold worker would
     download 7.3 GB first. The handler copes either way, but it would be slower.
   - FlashBoot: on. It is free and makes later cold starts quicker.
4. **Wait for the build:** the first build takes a while (torch alone is about 3 GB). The status shows
   under the endpoint's Builds tab.
5. **Local client config:** create a `.env` in this folder. It is gitignored.
   ```
   RUNPOD_API_KEY=...        # Runpod console → Settings → API Keys (a restricted key limited to this endpoint is enough)
   LTBR_ENDPOINT_ID=...      # shown on the endpoint page
   ```
6. **Smoke test:** `python3 client/ltbr_song.py --style up-and-out --lyrics client/example_lyrics.txt`.
   The first call waits for a worker to start and the model to load. Later calls only take the generation time.

Every push to `main` triggers a new build and rolls it out. To roll back, redeploy an earlier build from the console.

## Using it
Like Suno, each request gives **2 takes**:
- **Take A** uses the model defaults (guidance 1.0). It was the most reliable setting in the bake-off.
- **Take B** uses stronger style guidance (1.2) and the next seed. On average it was slightly worse, but it was
  the best take on some songs (Up and Out, Concrete Weather).

The takes run as parallel jobs. To explore other directions for B, edit `TAKE_PLAN` in `client/ltbr_song.py`.
The worker also accepts `semantic_sampling` / `abc_sampling` overrides (temperature, top_p, top_k,
repetition_penalty). `--takes 4` gives A, B, A2 and B2, each with a new seed.

```
python3 client/ltbr_song.py --list-styles
python3 client/ltbr_song.py --style ridley-road-market --lyrics news.txt          # takes A + B
python3 client/ltbr_song.py --style "English, 1980s UK lovers rock, ..." --lyrics news.txt --seed 7 --takes 4
python3 client/ltbr_song.py --health
python3 client/web.py          # http://localhost:8802
```
Each MP3 in `out/` is named `<time>-<style>-<take>-<seed>.mp3`. Beside it, a `.json` records the take's
settings, seed, timings, the lyrics as sent and the style. To re-make a take exactly, reuse the same settings.

The job API is a plain POST to `https://api.runpod.ai/v2/<endpoint>/run` with `{"input": {"style", "lyrics",
"seed"?, "cfg_scale"?, "semantic_sampling"?}}`, then polling `/status/<id>`. The radio system can call it the same
way the client does.

## Costs and limits
- **Price:** RTX 4090 serverless is $1.10/h, billed per second while a worker runs. A song is about
  80–100 s of GPU time, so about $0.03. Idle costs nothing, apart from the idle timeout after the last job.
- **Cold start:** a worker has to start and load about 8 GB of weights into the GPU. Expect up to a few minutes
  the first time an image lands on a machine, and well under a minute after that. Not measured yet; see
  `docs/STATUS.md`.
- **Job response size:** responses are capped at about 10 MB. A 4-minute MP3 at 192 kbps fits. The handler
  steps down the bitrate if a long song wouldn't fit.
- **Length:** YuE2 stops at about 6 minutes (9,000 tokens). Raw Suno lyrics with production notes can run to
  that cap, which is another reason to keep `clean_lyrics` on.
