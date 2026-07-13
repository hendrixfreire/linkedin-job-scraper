"""Dashboard local com fila, auditoria e feedback."""

from __future__ import annotations

import json
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .db import Database


HTML = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Candidatura Agent</title>
<style>
:root{--bg:#0b0b0b;--panel:#151515;--line:#303030;--text:#f0f0f0;--muted:#888;--accent:#d82424;--ok:#43b06b;--warn:#d9a441}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif}header{position:sticky;top:0;background:#0b0b0bea;border-bottom:1px solid var(--line);padding:22px 4vw;z-index:3;backdrop-filter:blur(10px)}h1{margin:0;font-size:21px;letter-spacing:-.03em}.kicker,.meta{font:10px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.12em;color:var(--muted)}main{padding:28px 4vw 80px;max-width:1450px;margin:auto}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin-bottom:24px}.stat{background:var(--panel);padding:18px}.stat b{display:block;font:28px ui-monospace,monospace;margin-top:8px}.toolbar{display:flex;gap:10px;align-items:center;justify-content:space-between;margin:22px 0}.grid{display:grid;gap:12px}.card{background:var(--panel);border:1px solid var(--line);padding:18px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px}.title{font-size:17px;font-weight:650}.company{color:#bbb;margin:6px 0}.score{font:22px ui-monospace,monospace;color:var(--ok);text-align:right}.tag{display:inline-block;border:1px solid var(--line);padding:4px 7px;border-radius:3px;font:9px ui-monospace,monospace;text-transform:uppercase;margin-right:5px}.feedback{display:flex;gap:6px;margin-top:14px;flex-wrap:wrap}.feedback input{flex:1;min-width:180px;background:#0d0d0d;border:1px solid var(--line);color:var(--text);padding:8px}.feedback button,.refresh{background:transparent;color:var(--text);border:1px solid var(--line);padding:8px 10px;cursor:pointer}.feedback button:hover,.refresh:hover{border-color:var(--accent)}a{color:#ddd}.empty{border:1px dashed var(--line);padding:30px;color:var(--muted)}@media(max-width:700px){.card{grid-template-columns:1fr}.score{text-align:left}}
</style></head><body>
<header><div class="kicker">Hermes / candidatura agent</div><h1>Operação de candidaturas</h1></header>
<main><section class="stats" id="stats"></section><div class="toolbar"><div class="meta" id="updated">carregando</div><button class="refresh" onclick="load()">Atualizar</button></div><section class="grid" id="jobs"></section></main>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function sendFeedback(id,rating){const reason=document.getElementById('reason-'+id).value;await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:id,rating,reason})});await load()}
async function load(){const d=await fetch('/api/snapshot').then(r=>r.json());document.getElementById('updated').textContent='atualizado '+new Date().toLocaleTimeString('pt-BR');const order=['submitted','qualified','blocked','rejected','dry_run'];document.getElementById('stats').innerHTML=order.map(k=>`<div class="stat"><span class="meta">${esc(k)}</span><b>${d.stats[k]||0}</b></div>`).join('');document.getElementById('jobs').innerHTML=d.jobs.length?d.jobs.map(j=>`<article class="card"><div><div class="title">${esc(j.title)}</div><div class="company">${esc(j.company)} · ${esc(j.location)}</div><span class="tag">${esc(j.status)}</span>${j.ats?`<span class="tag">${esc(j.ats)}</span>`:''}<div class="feedback"><input id="reason-${j.id}" placeholder="motivo opcional"><button onclick="sendFeedback(${j.id},'good')">Boa</button><button onclick="sendFeedback(${j.id},'bad')">Ruim</button><button onclick="sendFeedback(${j.id},'irrelevant')">Irrelevante</button></div><div style="margin-top:12px"><a href="${esc(j.source_url)}" target="_blank" rel="noreferrer">Abrir vaga</a></div></div><div class="score">${j.fit_score}/100</div></article>`).join(''):'<div class="empty">Nenhuma vaga no banco.</div>'}
load();setInterval(load,30000);
</script></body></html>"""


def dashboard_snapshot(db: Database) -> dict[str, Any]:
    jobs = db.list_jobs()
    stats = Counter(job["status"] for job in jobs)
    for job in jobs:
        for key in ("fit_reasons", "blockers"):
            try:
                job[key] = json.loads(job[key])
            except (TypeError, json.JSONDecodeError):
                job[key] = []
    return {"stats": dict(stats), "jobs": jobs, "feedback": db.list_feedback()[:100]}


def make_handler(db: Database):
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.request.settimeout(30)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, HTML.encode(), "text/html; charset=utf-8")
            elif path == "/api/snapshot":
                body = json.dumps(dashboard_snapshot(db), ensure_ascii=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            elif path == "/api/health":
                self._send(200, b'{"ok":true}', "application/json")
            else:
                self._send(404, b'{"error":"not found"}', "application/json")

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/api/feedback":
                self._send(404, b'{"error":"not found"}', "application/json")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                rating = payload.get("rating")
                if rating not in ("good", "bad", "irrelevant"):
                    raise ValueError("rating inválido")
                db.add_feedback(int(payload["job_id"]), rating, str(payload.get("reason") or "")[:500])
                self._send(200, b'{"ok":true}', "application/json")
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "config.json").read_text())
    db_path = Path(config["database"])
    if not db_path.is_absolute():
        db_path = root / db_path
    db = Database(db_path)
    db.initialize()
    port = int(config.get("dashboard_port", 8765))
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(db))
    print(f"Dashboard: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
