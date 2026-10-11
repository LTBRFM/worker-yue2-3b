"""A small local page for making songs: pick a station style (or write one), paste lyrics, get takes back.

    python client/web.py            # then open http://localhost:8802

Same config as ltbr_song.py (RUNPOD_API_KEY, LTBR_ENDPOINT_ID). Songs are saved to out/ and played from there.
Listens on 127.0.0.1 only; the API key never leaves this machine except to Runpod.
"""
from __future__ import annotations

import html
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ltbr_song as ls

PORT = 8802
EXAMPLE = (Path(__file__).parent / "example_lyrics.txt").read_text()
REQS: list[dict] = []  # newest first
LOCK = threading.Lock()


def run(req: dict) -> None:
    def log(msg: str) -> None:
        with LOCK:
            req["log"].append(f"{time.strftime('%H:%M:%S')} {msg}")

    try:
        files = ls.make(req["style"], req["lyrics"], req["takes"], req["seed"], req["cfg"], req["clean"], log)
        with LOCK:
            req["files"] = [f.name for f in files]
    except Exception as e:  # shown on the page
        log(f"error: {type(e).__name__}: {e}")
    with LOCK:
        req["done"] = True


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>LTBR song maker</title><style>
:root{--bg:#fafaf8;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e3e2dc;--accent:#2f5d8a}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#9b9a94;--card:#202020;--line:#33332f;--accent:#8db7e0}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:860px;padding:16px}
label{display:block;margin:10px 0 4px;font-weight:600} small,.log{color:var(--muted)}
select,textarea,input{width:100%;box-sizing:border-box;background:var(--card);color:var(--fg);border:1px solid var(--line);
border-radius:6px;padding:8px;font:inherit} textarea{min-height:90px} #lyrics{min-height:260px;font-family:ui-monospace,monospace;font-size:13px}
.row{display:flex;gap:12px;flex-wrap:wrap} .row>div{flex:1;min-width:140px}
button{margin-top:14px;background:var(--accent);color:var(--bg);border:0;border-radius:6px;padding:10px 18px;font:inherit;font-weight:600;cursor:pointer}
.req{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:12px 0}
.log{font:12px/1.4 ui-monospace,monospace;white-space:pre-wrap} audio{width:100%;margin:6px 0}
</style></head><body><h1>LTBR song maker</h1>
<p><small>YuE2 on Runpod serverless (RTX 4090). About 80 s per 3½-minute song once a worker is warm; the first request
after a quiet spell waits for a worker to start. Each take costs about $0.03.</small></p>
<form id="f"><label>Station style</label><select id="preset">__OPTIONS__<option value="">Custom (write below)</option></select>
<label>Style text <small>sent to the model; edit freely. Short and structured works best: language, genre and era,
vocal, instruments, tempo.</small></label><textarea id="style"></textarea>
<label>Lyrics <small>[Verse] [Chorus] [Bridge] [Outro] tags; Suno-style notes in brackets are removed</small></label>
<textarea id="lyrics">__EXAMPLE__</textarea>
<div class="row"><div><label>Takes <small>A = defaults, B = guidance 1.2</small></label><input id="takes" type="number" min="1" max="6" value="2"></div>
<div><label>Seed <small>blank = random</small></label><input id="seed" type="number"></div>
<div><label>Guidance <small>blank = per take</small></label><input id="cfg" type="number" step="0.1"></div></div>
<button>Make song</button></form><div id="reqs"></div>
<script>
const S=__STYLES__, $=id=>document.getElementById(id);
const fill=()=>{const p=$('preset').value; if(p) $('style').value=S[p].style};
$('preset').onchange=fill; fill();
$('f').onsubmit=async e=>{e.preventDefault();
  const body={style:$('style').value,lyrics:$('lyrics').value,takes:+$('takes').value||1,
    seed:$('seed').value===''?null:+$('seed').value,cfg:$('cfg').value===''?null:+$('cfg').value,name:$('preset').value};
  const r=await fetch('/api/make',{method:'POST',body:JSON.stringify(body)}); if(!r.ok) alert(await r.text()); load()};
const esc=s=>s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){const reqs=await (await fetch('/api/state')).json();
  $('reqs').innerHTML=reqs.map(q=>`<div class="req"><b>${esc(q.label)}</b> · ${q.takes} take(s) · ${q.when}${q.done?'':' · working…'}
   ${q.files.map(f=>`<div><small>take ${esc((f.match(/-([A-Z][0-9]*)-[0-9]+\\.mp3$/)||[,''])[1])} · ${esc(f)}</small><audio controls src="/out/${encodeURIComponent(f)}"></audio></div>`).join('')}
   <details ${q.done?'':'open'}><summary><small>log</small></summary><div class="log">${esc(q.log.join('\\n'))}</div></details></div>`).join('')}
load(); setInterval(load,4000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/":
            opts = "".join(f'<option value="{k}">{html.escape(v["label"])}</option>' for k, v in ls.STYLES.items())
            page = (PAGE.replace("__OPTIONS__", opts).replace("__EXAMPLE__", html.escape(EXAMPLE))
                    .replace("__STYLES__", json.dumps(ls.STYLES)))
            self.send(200, page.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            with LOCK:
                body = json.dumps([{k: q[k] for k in ("label", "takes", "when", "done", "files", "log")} for q in REQS])
            self.send(200, body.encode(), "application/json")
        elif self.path.startswith("/out/"):
            f = ls.OUT / Path(self.path[5:]).name  # name only: no path traversal
            if f.suffix == ".mp3" and f.is_file():
                self.send(200, f.read_bytes(), "audio/mpeg")
            else:
                self.send(404, b"not found", "text/plain")
        else:
            self.send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/api/make":
            return self.send(404, b"not found", "text/plain")
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not b.get("style", "").strip() or not b.get("lyrics", "").strip():
            return self.send(400, b"style and lyrics are required", "text/plain")
        name = b.get("name") or "custom"
        style = b["style"].strip()
        label = ls.STYLES[name]["label"] if name in ls.STYLES and ls.STYLES[name]["style"] == style else "Custom style"
        req = {"style": style, "lyrics": b["lyrics"], "takes": max(1, min(6, int(b.get("takes") or 2))),
               "seed": b.get("seed"), "cfg": b.get("cfg"), "clean": True, "label": label,
               "when": time.strftime("%H:%M"), "done": False, "files": [], "log": []}
        with LOCK:
            REQS.insert(0, req)
        threading.Thread(target=run, args=(req,), daemon=True).start()
        self.send(200, b"{}", "application/json")

    def log_message(self, *a) -> None:
        pass


if __name__ == "__main__":
    ls.config()  # fail early without credentials
    print(f"http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
