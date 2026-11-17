#!/usr/bin/env python3
"""Upload invscan's label designs to InvenTree (safe to re-run: existing ones are updated).

    INVENTREE_URL=... INVENTREE_TOKEN=... python scripts/install_labels.py
"""
import os
import sys
from pathlib import Path

import requests

URL = os.environ["INVENTREE_URL"].rstrip("/")
HEAD = {"Authorization": f"Token {os.environ['INVENTREE_TOKEN']}"}
HERE = Path(__file__).resolve().parent.parent / "label_templates"

DESIGNS = [
    # file, name shown in InvenTree, model, width mm, height mm, description
    ("invscan_bin_label.html", "invscan Bin Label (62x30)", "stocklocation", 62, 30,
     "QR plus the full place (room, cabinet, drawer) with the bin name large. For 62 mm tape."),
]


def main() -> int:
    existing = {t["name"]: t["pk"] for t in requests.get(f"{URL}/api/label/template/?limit=500", headers=HEAD, timeout=30).json().get("results", [])}
    for fname, name, model, w, h, desc in DESIGNS:
        data = {"name": name, "description": desc, "model_type": model, "width": w, "height": h, "enabled": "true", "filters": ""}
        files = {"template": (fname, (HERE / fname).read_bytes(), "text/html")}
        if name in existing:
            r = requests.patch(f"{URL}/api/label/template/{existing[name]}/", headers=HEAD, data=data, files=files, timeout=60)
            verb = "updated"
        else:
            r = requests.post(f"{URL}/api/label/template/", headers=HEAD, data=data, files=files, timeout=60)
            verb = "created"
        if not r.ok:
            print(f"{name}: failed {r.status_code} {r.text[:300]}", file=sys.stderr)
            return 1
        print(f"{name}: {verb} (id {r.json()['pk']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
