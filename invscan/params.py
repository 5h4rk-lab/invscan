"""Structured InvenTree part parameters (generic /parameter/ API, InvenTree >= 1.x)."""
import re

SKIP = {"DigiKey Programmable"}
_cache: dict[str, int] = {}


def _template(inv, name: str, description: str = "") -> int:
    if name in _cache:
        return _cache[name]
    for t in inv.list("parameter/template/", search=name):
        if t["name"] == name:
            _cache[name] = t["pk"]
            return t["pk"]
    pk = inv.post("parameter/template/", name=name, description=description, model_type="part.part")["pk"]
    _cache[name] = pk
    return pk


def set_param(inv, part_id: int, name: str, value: str, description: str = "") -> None:
    value = str(value).strip()[:500]
    if not value:
        return
    tpl = _template(inv, name, description)
    cur = inv.list("parameter/", model_type="part.part", model_id=part_id, template=tpl)
    if cur:
        if cur[0]["data"] != value:
            inv.patch(f"parameter/{cur[0]['pk']}/", data=value)
    else:
        inv.post("parameter/", template=tpl, model_type="part.part", model_id=part_id, data=value)


def set_digikey_params(inv, part_id: int, product: dict) -> int:
    n = 0
    for x in product.get("Parameters", []):
        name = re.sub(r"\s+", " ", x["ParameterText"]).strip()[:100]
        if name and name not in SKIP and x.get("ValueText", "").strip() not in ("", "-"):
            set_param(inv, part_id, name, x["ValueText"], "From DigiKey")
            n += 1
    return n


def mark_scanned(inv, part_id: int, when: str) -> None:
    set_param(inv, part_id, "Last Scanned", when, "Date this part was last scanned in (YYYY-MM-DD)")
