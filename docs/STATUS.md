# Status

## 2026-10-11: built, not yet deployed
- Code written; the image was built locally to check that it builds. There is no GPU on the dev box, so it has not run here.
- Waiting on the owner:
  - create the GitHub repo and push;
  - connect Runpod to GitHub;
  - create the endpoint (README "One-time setup");
  - put the API key and endpoint ID in `.env`.
- Then:
  - smoke test, recording cold-start time (delayTime), load time and generation time;
  - confirm the cached model is found (the job output's `weights` field should say `runpod-cache`).
- **Not verified yet:** where Runpod mounts the cached model. The handler looks in
  `/runpod-volume/huggingface-cache/hub` (Runpod's documented location) and falls back to a Hub download.
- The stopped bake-off pod `pi98fcnvncjb5p` and its 150 GB disk can be terminated once this works.
