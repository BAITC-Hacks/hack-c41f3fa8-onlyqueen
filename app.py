from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.recommender import Recommender


ROOT = Path(__file__).resolve().parent
ENGINE = Recommender(ROOT / "data" / "profiles.csv")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "static"), **kwargs)

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/meta":
            return self._json(ENGINE.metadata())
        if self.path == "/health":
            return self._json({"ok": True, "profiles": len(ENGINE.profiles)})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/recommend":
            return self._json({"error": "Не найдено"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            compare_date = payload.pop("compare_date", "")
            result = ENGINE.compare(payload, compare_date) if compare_date else {"primary": ENGINE.recommend(payload)}
            return self._json(result)
        except (ValueError, json.JSONDecodeError) as exc:
            return self._json({"error": str(exc)}, 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"MVP запущен: http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
