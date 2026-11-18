#!/usr/bin/env python3
"""Give parts that have no picture one, from DigiKey, by manufacturer part number (safe to re-run).

    INVENTREE_URL=... INVENTREE_TOKEN=... DIGIKEY_CLIENT_ID=... DIGIKEY_CLIENT_SECRET=... python scripts/backfill_images.py [--dry-run]

Mouser parts often have none, because Mouser's image server refuses downloads made by a script."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from invscan.client import InvenTree  # noqa: E402
from invscan.digikey import DigiKey  # noqa: E402
from invscan.enrich import set_image  # noqa: E402


def backfill(inv, dk, dry_run=False) -> dict:
    done, missed = [], []
    for p in inv.list("part/", limit=1000):
        if p.get("image") or p.get("is_template"):
            continue
        mps = inv.list("company/part/manufacturer/", part=p["pk"], manufacturer_detail="true")
        mp = mps[0] if mps else None
        mpn = mp["MPN"] if mp else p["name"]
        maker = ((mp or {}).get("manufacturer_detail") or {}).get("name")
        prod = dk.lookup(mpn, None, maker)
        if not (prod and prod.get("PhotoUrl")):
            missed.append(p["name"]); continue
        if dry_run or set_image(inv, p["pk"], mpn, prod["PhotoUrl"]):
            done.append(p["name"])
        else:
            missed.append(p["name"])
    return {"added": done, "none_found": missed}


if __name__ == "__main__":
    r = backfill(InvenTree(), DigiKey(), "--dry-run" in sys.argv)
    print(f"pictures {'to add' if '--dry-run' in sys.argv else 'added'}: {len(r['added'])}", *r["added"], sep="\n  ")
    print(f"no picture found: {len(r['none_found'])}", *r["none_found"], sep="\n  ")
