"""Label printing through InvenTree's label API: a machine (e.g. Brother QL) if usable, else a PDF."""
import time

MODELS = ("stocklocation", "part", "stockitem")


def templates_by_model(inv) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for t in inv.list("label/template/", enabled="true", limit=200):
        if t["model_type"] in MODELS:
            out.setdefault(t["model_type"], []).append(
                {"id": t["pk"], "name": t["name"], "size": f"{t['width']:g}x{t['height']:g} mm"})
    return out


def printers(inv) -> list[dict]:
    res = []
    for m in inv.list("machine/"):
        if m.get("machine_type") != "label-printer":
            continue
        errs = m.get("machine_errors") or []
        ok = bool(m.get("active") and m.get("is_driver_available") and not errs)
        res.append({"id": m["pk"], "name": m["name"], "ok": ok, "error": "; ".join(errs)})
    return res


def plan_print(model: str, templates: dict, machines: list[dict], machine: str | None, template: int | None) -> dict:
    """Decide template + output. Uses a printer when it is healthy, otherwise falls back to a PDF."""
    avail = templates.get(model, [])
    if template is None and avail:
        # our own design shows the whole place (room, cabinet, drawer); else a QR + text label is handy on bins
        pref = ([t for t in avail if t["name"].lower().startswith("invscan")]
                or [t for t in avail if "QR + Text" in t["name"]] or avail)
        template = pref[0]["id"]
    chosen = next((m for m in machines if m["id"] == machine), None) if machine else next((m for m in machines if m["ok"]), None)
    if chosen and chosen["ok"]:
        return {"plugin": "inventreelabelmachine", "machine": chosen["id"], "template": template, "fallback": ""}
    why = ""
    if chosen:
        why = f'{chosen["name"]} is not available ({chosen["error"] or "inactive"}). Made a PDF instead.'
    return {"plugin": "inventreelabel", "machine": None, "template": template, "fallback": why}


def run_print(inv, model: str, ids: list[int], plan: dict, timeout: float = 25.0) -> dict:
    body = {"template": plan["template"], "plugin": plan["plugin"], "items": ids}
    if plan["machine"]:
        body["machine"] = plan["machine"]
    job = inv.post("label/print/", **body)
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = inv.get(f"data-output/{job['pk']}/")
        if j.get("errors"):
            return {"ok": False, "mode": "printer" if plan["machine"] else "pdf", "message": str(j["errors"])}
        if j.get("complete"):
            if plan["machine"]:
                return {"ok": True, "mode": "printer", "message": "Sent to the printer."}
            return {"ok": True, "mode": "pdf", "url": j.get("output"), "message": plan["fallback"] or "PDF ready."}
        time.sleep(0.5)
    return {"ok": False, "mode": "printer" if plan["machine"] else "pdf", "message": "Timed out waiting for InvenTree."}
