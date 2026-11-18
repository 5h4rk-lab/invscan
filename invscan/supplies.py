"""Power supplies: one template part per model (LRS-350), one variant per configuration (24V), stock on the variants.

Spec parameters use DigiKey's own names, so supplies you type in and supplies bought from DigiKey share filters."""
import re
from datetime import date

from .categories import ensure_category_path
from .enrich import ensure_manufacturer_part
from .ingest import Result, elsewhere
from .locations import ensure_path
from .notes import set_note
from .params import mark_scanned, set_param

ROOT = ["Supplies", "Power Supplies"]
KINDS = ["AC-DC Enclosed", "DIN Rail", "Wall Adapters", "Bench Supplies", "DC-DC Modules", "USB Chargers"]


def ensure_categories(inv) -> dict[str, int]:
    """{kind name: category id}, plus 'Power Supplies' for the root. Creates anything missing."""
    out = {"Power Supplies": ensure_category_path(inv, ROOT)}
    for k in KINDS:
        out[k] = ensure_category_path(inv, ROOT + [k])
    return out


def _num(text, unit: str) -> str:
    """'24', '24v', '24 V' -> '24V'; '' stays ''. Raises ValueError for something that is not a number."""
    t = re.sub(rf"\s*{unit}$", "", str(text or "").strip(), flags=re.I)
    if not t:
        return ""
    return f"{float(t):g}{unit}"


def models(inv) -> list[dict]:
    """Every supply model with its variants and the stock on hand."""
    root = next((c["pk"] for c in inv.list("part/category/", limit=1000)
                 if c.get("pathstring") == "/".join(ROOT)), None)
    if not root:
        return []  # nothing added yet; the categories appear with the first supply
    parts = inv.list("part/", category=root, limit=1000)
    kids: dict[int, list] = {}
    for p in parts:
        if p.get("variant_of"):
            kids.setdefault(p["variant_of"], []).append(
                {"id": p["pk"], "name": p["name"], "stock": p.get("total_in_stock") or 0})
    return [{"id": p["pk"], "name": p["name"], "description": p.get("description", ""), "category": p.get("category"),
             "variants": sorted(kids.get(p["pk"], []), key=lambda v: v["name"])}
            for p in parts if p.get("is_template")]


def _find_template(inv, model: str):
    for p in inv.list("part/", search=model, is_template="true", limit=50):
        if p["name"].lower() == model.lower():
            return p
    return None


def add_power_supply(inv, model: str, voltage: str, current: str, qty: int, location_id: int | None, note: str | None,
                     kind: str = "", maker: str = "", watts: str = "", input_range: str = "", connector: str = "",
                     mounting: str = "", description: str = "") -> Result:
    model = " ".join((model or "").split())
    if not model:
        return Result("error", message="enter the model, for example LRS-350")
    if not qty or qty <= 0:
        return Result("error", message="enter a quantity")
    if not location_id and not (note or "").strip():
        return Result("error", message="no bin and no note: say where it went")
    try:
        volts, amps = _num(voltage, "V"), _num(current, "A")
        power = _num(watts, "W")
    except ValueError:
        return Result("error", message="voltage, current and watts must be numbers")
    if not volts:
        return Result("error", message="enter the output voltage: it tells the configurations apart")
    if not power and amps:
        power = f"{float(volts[:-1]) * float(amps[:-1]):.0f}W"

    cats = ensure_categories(inv)
    template = _find_template(inv, model)
    category = (template or {}).get("category") or cats.get(kind) or cats["Power Supplies"]
    maker = (maker or "").strip()
    if template:
        tid = template["pk"]
    else:
        tid = inv.post("part/", name=model, IPN=model, category=category, is_template=True, component=True,
                       purchaseable=True, description=description or f"{maker + ' ' if maker else ''}{model} power supply")["pk"]
        if maker:
            ensure_manufacturer_part(inv, tid, maker, model)

    name = f"{model} {volts}"
    variant = next((p for p in inv.list("part/", search=model, limit=100)
                    if p["name"].lower() == name.lower() and p.get("variant_of") == tid), None)
    new_part = variant is None
    if new_part:
        vid = inv.post("part/", name=name, IPN=name, category=category, variant_of=tid, component=True, purchaseable=True,
                       keywords=" ".join(x for x in (model, maker, volts, amps, power, "power supply") if x)[:250],
                       description=description or f"{volts} {amps} {power} power supply".replace("  ", " ").strip())["pk"]
        if maker:
            ensure_manufacturer_part(inv, vid, maker, model)
    else:
        vid = variant["pk"]
    for k, v in (("Voltage - Output 1", volts), ("Current - Output (Max)", amps), ("Power (Watts)", power),
                 ("Voltage - Input", input_range), ("Mounting Type", mounting), ("Connector", connector)):
        set_param(inv, vid, k, v, "Power supply specification")

    where = location_id or ensure_path(inv, "Unplaced")
    item = inv.post("stock/", part=vid, quantity=int(qty), location=where, notes=set_note("", note))
    if isinstance(item, list):
        item = item[0]
    try:
        mark_scanned(inv, vid, date.today().isoformat())
    except RuntimeError:
        pass
    return Result("created", vid, item["pk"], new_part, "", [] if new_part else elsewhere(inv, vid, item["pk"]))
