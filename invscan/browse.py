"""Browse parts by category with DigiKey-style filters built from the specs stored as InvenTree parameters."""
import re
import time

HIDDEN = {"Last Scanned", "Category lookup"}  # our own bookkeeping, not specs
_cache: dict = {"t": 0.0, "idx": {}}
TTL = 30.0
COLUMNS = 5  # spec columns in the results table


def natural_key(s: str):
    """'4.7 uF' < '22 uF' < '100 uF': numbers compare as numbers. Every chunk is (kind, number, text) so a name that
    starts with a digit and one that starts with a letter can still be compared."""
    return [(0, float(x), "") if re.fullmatch(r"\d+(?:\.\d+)?", x) else (1, 0.0, x.lower())
            for x in re.split(r"(\d+(?:\.\d+)?)", s) if x != ""]


def param_index(inv, force: bool = False) -> dict[int, dict[str, str]]:
    """{part id: {spec name: value}} for every part (InvenTree cannot return parts with their specs, so fetch them
    all and keep them for a few seconds)."""
    if not force and time.time() - _cache["t"] < TTL and _cache["idx"]:
        return _cache["idx"]
    names = {t["pk"]: t["name"] for t in inv.list("parameter/template/", limit=1000)}
    idx: dict[int, dict[str, str]] = {}
    offset = 0
    while True:
        page = inv.get("parameter/", model_type="part.part", limit=1000, offset=offset)
        rows = page["results"] if isinstance(page, dict) else page
        for r in rows:
            n = names.get(r["template"])
            if n and n not in HIDDEN and (r.get("data") or "").strip():
                idx.setdefault(r["model_id"], {})[n] = r["data"].strip()
        offset += 1000
        if not isinstance(page, dict) or not page.get("next") or not rows:
            break
    _cache.update(t=time.time(), idx=idx)
    return idx


def invalidate() -> None:
    _cache.update(t=0.0, idx={})


def compute_facets(items: list[dict], selected: dict[str, list[str]], max_facets: int = 8, max_values: int = 12):
    """Filter `items` ([{'id', 'params': {name: value}}]) by the selected facet values and list the facets that are
    still worth showing. Values inside one facet are OR, different facets are AND. Each facet's counts ignore its own
    selection, so you can switch to another value without clearing it first."""
    def ok(it, skip=None):
        return all(it["params"].get(n) in vals for n, vals in selected.items() if vals and n != skip)

    ids = [it["id"] for it in items if ok(it)]
    names: dict[str, int] = {}
    for it in items:
        for n in it["params"]:
            names[n] = names.get(n, 0) + 1
    facets = []
    for n, covered in names.items():
        distinct = {it["params"][n] for it in items if n in it["params"]}
        keep = n in selected and selected[n]
        if not keep and (len(distinct) < 2 or covered / max(1, len(items)) < 0.3):
            continue
        counts: dict[str, int] = {}
        for it in items:
            if n in it["params"] and ok(it, skip=n):
                counts[it["params"][n]] = counts.get(it["params"][n], 0) + 1
        for v in selected.get(n, []):
            counts.setdefault(v, 0)
        vals = sorted(counts.items(), key=lambda kv: (-kv[1], natural_key(kv[0])))
        shown = vals[:max_values] + [kv for kv in vals[max_values:] if kv[0] in selected.get(n, [])]
        facets.append({"name": n, "coverage": covered, "values": [
            {"value": v, "count": c, "selected": v in selected.get(n, [])} for v, c in shown]})
    facets.sort(key=lambda f: (not any(v["selected"] for v in f["values"]), -f["coverage"], f["name"]))
    return ids, facets[:max_facets] + [f for f in facets[max_facets:] if any(v["selected"] for v in f["values"])]


def browse(inv, category: int | None, q: str, sort: str, selected: dict[str, list[str]], wide: bool = False) -> dict:
    """wide: every filter and every value (for the filter panel and table), not just the handful a phone sheet can hold."""
    query = {"limit": 1000}
    if category:
        query.update(category=category, cascade="true")
    if q:
        query["search"] = q
    parts = inv.get("part/", **query)
    parts = parts["results"] if isinstance(parts, dict) else parts
    idx = param_index(inv)
    ids, facets = compute_facets([{"id": p["pk"], "params": idx.get(p["pk"], {})} for p in parts], selected,
                                 max_facets=40 if wide else 8, max_values=300 if wide else 12)
    keep = set(ids)
    coverage: dict[str, int] = {}  # which specs most of the results have: they become the table's columns
    for p in parts:
        if p["pk"] in keep:
            for n in idx.get(p["pk"], {}):
                coverage[n] = coverage.get(n, 0) + 1
    columns = [n for n, _ in sorted(coverage.items(), key=lambda kv: (-kv[1], kv[0]))][:COLUMNS]
    rows = []
    for p in parts:
        if p["pk"] not in keep:
            continue
        specs = idx.get(p["pk"], {})
        shown = [n for n in selected if n in specs] + [n for n in specs if n not in selected]
        rows.append({"id": p["pk"], "name": p["name"], "description": p["description"], "thumbnail": p.get("thumbnail"),
                     "total": p.get("total_in_stock") or 0, "category": p.get("category_name"), "category_id": p.get("category"),
                     "created": p.get("creation_date") or "", "specs": [{"name": n, "value": specs[n]} for n in shown[:3]],
                     "cols": {n: specs.get(n, "") for n in columns}})
    if sort == "name":
        rows.sort(key=lambda r: natural_key(r["name"]))
    elif sort == "stock":
        rows.sort(key=lambda r: -r["total"])
    elif sort == "newest":
        rows.sort(key=lambda r: r["created"], reverse=True)
    return {"total": len(rows), "parts": rows[:1000 if wide else 200], "facets": facets, "columns": columns}
