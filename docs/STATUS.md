# Status

## 2026-10-11: deployed and working
- Endpoint `mkp6hxsxiwhhne` (worker-yue2-3b) is built by Runpod from `LTBRFM/worker-yue2-3b` `main`.
  - RTX 4090 pool ADA_24, CUDA 12.8 to 13.4, 0–2 workers, idle 30 s, timeout 900 s, FlashBoot on.
  - Cached model `m-a-p/YuE2-3B`.
- **Cached model works:** the worker finds it at `/runpod-volume/huggingface-cache/hub/models--m-a-p--YuE2-3B/
  snapshots/8f24312f…`. The pipeline is ready 5 s after the container starts, and weights load during the first job.
- **Measured:**

  | Run | Waited in queue | Generation | Song length |
  |---|---|---|---|
  | First job | 593 s, almost all of it the first image build | 41 s | 98.6 s |
  | Two-take request from idle (scaled to zero, FlashBoot): take A | 6 s | 34.5 s | 106 s |
  | Same request: take B (cfg 1.2) | 13 s | 52.6 s | 121 s |

  - The two takes ran in parallel on two workers.
  - A two-take request comes back in about a minute.
  - The cost is about $0.03 per take.
- **Not yet measured:** a cold start on a host that has never pulled the image. That happens when Runpod moves
  workers to new machines; expect minutes.

## Next
- Listen to the takes in `out/`. If take B's direction is wrong, change `TAKE_PLAN` in the client.
- Possible: an LLM step that turns a news item into lyrics and the condensed style.
- Settle the licence before broadcast (see README).
