import os
import requests


class InvenTree:
    def __init__(self, url: str | None = None, token: str | None = None):
        self.url = (url or os.environ["INVENTREE_URL"]).rstrip("/")
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Token {token or os.environ['INVENTREE_TOKEN']}"

    def _req(self, method, path, **kw):
        r = self.s.request(method, f"{self.url}/api/{path.lstrip('/')}", timeout=20, **kw)
        if not r.ok:
            raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else None

    def get(self, path, **params):
        return self._req("GET", path, params=params)

    def list(self, path, **params):
        d = self.get(path, **params)
        return d["results"] if isinstance(d, dict) else d

    def post(self, path, **body):
        return self._req("POST", path, json=body)

    def patch(self, path, **body):
        return self._req("PATCH", path, json=body)

    def delete(self, path):
        return self._req("DELETE", path)

    def patch_file(self, path, field, filename, data: bytes):
        return self._req("PATCH", path, files={field: (filename, data)})
