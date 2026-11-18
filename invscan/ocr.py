"""Pull part-number candidates out of OCR'd label text, for labels with no readable square code.

OCR on a glossy bag is noisy (O for 0, G for 6, $ for S), so the page reads the label at several angles and sends all the
text. Here the candidates are ranked and given look-alike corrections; DigiKey's search then decides, and the person confirms."""
import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .parser import DK_PN

LABELS = {"1P", "30P", "MPN", "P/N", "PN", "TYPE", "PART", "PARTNO", "PARTNUMBER", "MFRPART", "MFGPART", "MODEL"}
STOP = {"TYPE", "CODENO", "PART", "NO", "NUMBER", "QTY", "LOT", "DATE", "COUNTRY", "ORIG", "HALOGEN", "COMPLIANT", "ROHS",
        "SEMICONDUCTORS", "ASSEMBLY", "DIFFUSION", "SEALED", "UNITED", "STATES", "CHINA", "MALAYSIA", "TAIWAN", "PUID"}
_TOKEN = re.compile(r"[A-Z0-9$][A-Z0-9$._/+\-]{3,29}")
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
# captions whose value is never the part number: the next word or two after them are dates, lot codes, bag ids...
NOT_PART = {"DATE", "SEALED", "LOT", "PUID", "QTY", "QUANTITY", "ORIG", "PMC", "MSL", "MSL/PBT", "COUNTRY", "CODE", "DC", "D/C",
            "EXP", "EXPIRES", "MFG", "MFD", "PKG", "PACKED", "INVOICE", "ORDER", "PO", "SO", "BATCH", "SERIAL", "SN", "WEIGHT"}


def _is_date(tok: str) -> bool:
    """06NOV26, 06-NOV-2026, NOV-06-26 and the same with OCR slips (O for 0, I for 1)."""
    t = tok.upper()
    m = re.fullmatch(r"([0-9OIL]{1,2})[-/. ]?([A-Z0]{3})[-/. ]?([0-9OIL]{2,4})", t)
    if m and m.group(2).replace("0", "O") in MONTHS:
        return True
    m = re.fullmatch(r"([A-Z0]{3})[-/. ]?([0-9OIL]{1,2})[-/. ,]*([0-9OIL]{2,4})", t)
    return bool(m and m.group(1).replace("0", "O") in MONTHS)


@dataclass
class Extracted:
    dk_pn: str | None = None
    qty: int | None = None
    lot: str = ""
    date_code: str = ""
    labelled: list[str] = field(default_factory=list)  # tokens that followed a "TYPE" or "1P" style caption
    generic: list[str] = field(default_factory=list)  # other part-number-looking tokens, most repeated first
    queries: list[str] = field(default_factory=list)


def _clean(tok: str) -> str:
    return tok.replace("$", "S").strip(".,;:()[]|_-/")


def variants(tok: str) -> list[str]:
    """The token itself plus corrections for the usual OCR mix-ups, most likely first."""
    def fix_o(t, everywhere=False):
        if everywhere:
            return t.replace("O", "0")
        for _ in range(2):  # a fixed O can make its neighbour an 'adjacent digit' in turn
            t = re.sub(r"(?<=\d)O|O(?=\d)", "0", t)
        return t

    def fix_g(t):
        return re.sub(r"(?<=[\d])G|G(?=[0])", "6", t)

    out = [tok]
    digits = sum(c.isdigit() for c in tok)
    for cand in (fix_o(tok), fix_g(fix_o(tok)), fix_o(tok, everywhere=digits >= 2), fix_g(fix_o(tok, everywhere=digits >= 2))):
        if cand not in out:
            out.append(cand)
    return out[:4]


def similarity(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def _plausible(tok: str) -> bool:
    return (6 <= len(tok) <= 30 and any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok)
            and tok not in STOP and not _is_date(tok) and not DK_PN.match(tok))


def _shape(tok: str) -> float:
    """How much a token looks like a manufacturer part number: letters and digits mixed, a usable length."""
    letters, digits = sum(c.isalpha() for c in tok), sum(c.isdigit() for c in tok)
    return (1.0 if min(letters, digits) >= 2 else 0.0) + (1.0 if 8 <= len(tok) <= 20 else 0.0) + (0.5 if letters >= 3 else 0.0)


def extract(text: str) -> Extracted:
    up = (text or "").upper()
    ex = Extracted()
    flat = re.sub(r"\s*-\s*", "-", up)  # OCR sometimes spaces out the hyphens
    m = re.search(r"\b\d{1,6}-[A-Z0-9][A-Z0-9._/+%()\-]*-ND\b", flat)
    ex.dk_pn = m.group(0) if m else None

    q = Counter(int(n) for n in re.findall(r"(?:QTY\.?|QUANTITY)[:\s]+(\d{1,6})\b", up))
    ex.qty = q.most_common(1)[0][0] if q else None
    lots = Counter(_clean(x) for x in re.findall(r"\bLOT[:#\s]*([A-Z0-9][A-Z0-9.\-/]{3,})", up))
    ex.lot = next((k for k, _ in lots.most_common() if len(k) >= 4 and any(c.isdigit() for c in k)), "")
    dates = Counter(re.findall(r"\bDATE(?:\s*CODE)?[:\s]*(\d{4})\b", up))
    ex.date_code = dates.most_common(1)[0][0] if dates else ""

    labelled, seen = [], Counter()
    for line in up.splitlines():
        words = line.split()
        for i, w in enumerate(words):
            if re.sub(r"[^A-Z0-9/]", "", w) in LABELS:
                for nxt in words[i + 1:i + 4]:
                    tok = _clean(nxt)
                    if tok in STOP or tok in LABELS or re.sub(r"[^A-Z0-9]", "", tok) in LABELS:
                        continue
                    if _TOKEN.fullmatch(tok) and _plausible(tok):
                        labelled.append(tok)
                    break
    skip = set()
    for line in up.replace("$", "S").splitlines():
        words = line.split()
        for i, w in enumerate(words):
            if re.sub(r"[^A-Z0-9/]", "", w) in NOT_PART:
                skip.update(_clean(x) for x in words[i + 1:i + 3])
    for tok in map(_clean, _TOKEN.findall(up.replace("$", "S"))):
        if _plausible(tok) and tok not in skip:
            seen[tok] += 1
    ex.labelled = list(dict.fromkeys(labelled))
    ex.generic = [t for t in sorted(seen, key=lambda t: -(_shape(t) + min(seen[t], 3))) if t not in ex.labelled and t != ex.lot]
    queries = ([ex.dk_pn] if ex.dk_pn else [])
    for t in ex.labelled[:2]:
        queries += variants(t)
    queries += ex.generic[:3]
    ex.queries = list(dict.fromkeys(queries))[:8]
    return ex


def _card(p: dict) -> dict:
    from .enrich import pick_description
    vs = p.get("ProductVariations") or []
    return {"mpn": p["ManufacturerProductNumber"], "manufacturer": p["Manufacturer"]["Name"],
            "description": pick_description(p)[:140], "photo": p.get("PhotoUrl") or "",
            "dk_pn": vs[0]["DigiKeyProductNumber"] if vs else ""}


def find_parts(dk, queries: list[str], dk_pn: str | None = None, limit: int = 8, min_score: float = 0.0) -> list[dict]:
    """DigiKey parts that match what the OCR read, closest first. Stops early once a query matches a part number exactly."""
    found: dict[tuple, dict] = {}

    def add(p, score):
        c = _card(p)
        key = (c["mpn"].upper(), c["manufacturer"].upper())
        if key not in found or score > found[key]["score"]:
            found[key] = {**c, "score": round(score, 3)}

    if dk_pn:
        p = dk.lookup(dk_pn, dk_pn)
        if p:
            add(p, 1.0)
            return list(found.values())
    for q in queries:
        if q == dk_pn:
            continue
        best = 0.0
        for p in dk.search(q, 5):
            s = similarity(p["ManufacturerProductNumber"], q)
            best = max(best, s)
            add(p, s)
        if best >= 0.97:
            break
    return sorted((c for c in found.values() if c["score"] >= min_score), key=lambda c: -c["score"])[:limit]
