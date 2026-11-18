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
# where the app lives: a cabinet label's QR is a link to it, so a phone camera opens "what is in here". Changing it later
# means reprinting those labels (the app still reads older ones).
APP_URL = os.environ.get("INVSCAN_URL", "https://invscan-eight.vercel.app").rstrip("/")
import base64

HERE = Path(__file__).resolve().parent.parent / "label_templates"
MARKS = HERE / "marks"

DESIGNS = [
    # file, name shown in InvenTree, model, width mm, height mm, description, expression naming the owner (or None)
    ("invscan_bin_label.html", "invscan Bin Label (62x30)", "stocklocation", 62, 30,
     "QR plus the full place (room, cabinet, drawer) with the bin name large. For 62 mm tape.", "location.owner"),
    ("invscan_stock_label.html", "invscan Stock Label (62x30)", "stockitem", 62, 30,
     "QR that opens the item, part name, description, quantity and place. For 62 mm tape.", "item.owner"),
    ("invscan_part_label.html", "invscan Part Label (62x30)", "part", 62, 30,
     "QR that opens the part, name, description and part number. For 62 mm tape.", "part.responsible"),
]


def _img(path: Path, cls: str = "mark") -> str:
    return f'<img class="{cls}" alt="" src="data:image/png;base64,{base64.b64encode(path.read_bytes()).decode()}">'


def mark_block(owner_expr: str | None) -> str:
    """The corner marks: always the logo (MARKS/logo.png if you have one, else the generic hen), and, when MARKS has
    owner_<NAME>.png (name as shown by InvenTree, e.g. owner_EV.png for the user 'EV'), that owner's picture beside it."""
    logo = MARKS / "logo.png" if (MARKS / "logo.png").exists() else MARKS / "hen.png"
    out = _img(logo) if logo.exists() else ""
    if not owner_expr:
        return out
    branches = []
    for f in sorted(MARKS.glob("owner_*.png")):
        stem = f.stem[len("owner_"):]
        label = stem[:-len("_group")] + " (group)" if stem.endswith("_group") else stem + " (user)"
        branches.append((label, _img(f, "mark owner")))
    for i, (label, tag) in enumerate(branches):
        out += ("{% if " if i == 0 else "{% elif ") + f'{owner_expr}|stringformat:"s" == "{label}" %}}' + tag
    return out + ("{% endif %}" if branches else "")


def main() -> int:
    existing = {t["name"]: t["pk"] for t in requests.get(f"{URL}/api/label/template/?limit=500", headers=HEAD, timeout=30).json().get("results", [])}
    for fname, name, model, w, h, desc, owner_expr in DESIGNS:
        data = {"name": name, "description": desc, "model_type": model, "width": w, "height": h, "enabled": "true", "filters": ""}
        body = (HERE / fname).read_text().replace("__MARK__", mark_block(owner_expr)).replace("__APP_URL__", APP_URL)
        files = {"template": (fname, body.encode(), "text/html")}
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
