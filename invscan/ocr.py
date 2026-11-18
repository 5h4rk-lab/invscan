"""Pull part-number candidates out of OCR'd label text, for labels with no readable square code.

OCR on a glossy bag is noisy (O for 0, G for 6, $ for S), so the page reads the label at several angles and sends all the
text. Here the candidates are ranked and given look-alike corrections; DigiKey's search then decides, and the person confirms."""
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations, product
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
    """06NOV26, 06-NOV-2026, 29-OCT, NOV-06-26 and the same with OCR slips (O for 0, I for 1); the year is optional."""
    t = tok.upper().strip(".,;:")
    for pat in (r"([0-9OIL]{1,2})[-/. ]?([A-Z0]{3})(?:[-/. ,]?([0-9OIL]{2,4}))?", r"([A-Z0]{3})[-/. ]?([0-9OIL]{1,2})(?:[-/. ,]*([0-9OIL]{2,4}))?"):
        m = re.fullmatch(pat, t)
        if m:
            month = m.group(2) if pat.startswith("([0-9") else m.group(1)
            if month.replace("0", "O") in MONTHS:
                return True
    return False


@dataclass
class Extracted:
    dk_pn: str | None = None  # the DigiKey number (ends in -ND) the label shows, the surest thing to search for
    dk_pns: list[str] = field(default_factory=list)  # all of them, most repeated first (a photo can show several bags)
    qty: int | None = None
    lot: str = ""
    date_code: str = ""
    dk_guesses: list[str] = field(default_factory=list)  # DigiKey-number-shaped but damaged (P19B0CT-AD): corrected before lookup
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


# what OCR mistakes for what, most common first (8/B, 0/O/Q/D, 5/S, 1/I/L ...; 9 for 5 and @ for 0 were seen on real labels)
CONFUSED = {"B": "8", "8": "B", "0": "QOD", "O": "0", "Q": "0", "D": "0", "@": "0", "1": "IL", "I": "1", "L": "1", "5": "S9",
            "S": "5", "9": "5", "2": "Z", "Z": "2", "6": "G", "G": "6", "V": "Y", "Y": "V"}


def fuzz(tok: str, cap: int = 12) -> list[str]:
    """Corrections of one or two look-alike characters, single changes first. Never includes the token itself."""
    spots = [(i, CONFUSED[c]) for i, c in enumerate(tok) if c in CONFUSED]
    out: list[str] = []
    for n in (1, 2):
        for chosen in combinations(spots, n):
            for repl in product(*(opts for _, opts in chosen)):
                t = list(tok)
                for (i, _), r in zip(chosen, repl):
                    t[i] = r
                out.append("".join(t))
                if len(out) >= cap:
                    return out
    return out


def digikey_guesses(text: str) -> list[str]:
    """Tokens that look like a DigiKey number whose ending OCR damaged (P19B0CT-AD): shaped '<body>-<2 chars ending D/0/O>'."""
    t = re.sub(r"[\u2010-\u2015\u2212]", "-", text.upper().replace("@", "0"))
    t = re.sub(r"\s*-\s*", "-", t)
    good = set(digikey_numbers(t))
    found = Counter()
    for tok in re.findall(r"[A-Z0-9][A-Z0-9._/+%()]{3,40}-[A-Z0-9][D0O]\b", t):
        body = tok.rsplit("-", 1)[0]
        pn = f"{body}-ND"
        if len(body) >= 5 and any(c.isdigit() for c in body) and any(c.isalpha() for c in body) and pn not in good and not _is_date(tok):
            found[pn] += 1
    return [pn for pn, _ in found.most_common()]


def digikey_numbers(text: str) -> list[str]:
    """DigiKey part numbers in OCR text, e.g. 296-19733-5-ND. Forgives what OCR does to them: long dashes, spaces around
    the hyphens, a missing hyphen before ND, ND read as NO or N0, and O/I/L for 0/1 in the leading digits."""
    t = re.sub(r"[\u2010-\u2015\u2212]", "-", text.upper())
    t = re.sub(r"\s*-\s*", "-", t)
    found = Counter()
    for tok in re.findall(r"[A-Z0-9][A-Z0-9._/+%()\-]{4,60}", t):
        if tok.endswith("-ND") and DK_PN.match(tok):  # a clean number: letters may lead (P15BQCT-ND)
            found[tok] += 1
            continue
        m = re.fullmatch(r"([0-9OIL]{1,6})-([A-Z0-9][A-Z0-9._/+%()\-]*?)-?N[D0O]", tok)
        if not m or not any(c.isdigit() for c in m.group(2)):
            continue
        lead = m.group(1).translate(str.maketrans("OIL", "011"))
        pn = f"{lead}-{m.group(2).strip('-')}-ND"
        if DK_PN.match(pn):
            found[pn] += 1
    return [pn for pn, _ in found.most_common()]


def similarity(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def _plausible(tok: str) -> bool:
    return (6 <= len(tok) <= 30 and any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok)
            and tok not in STOP and not _is_date(tok) and not DK_PN.match(tok)
            and not tok.startswith(("DIGI-KEY", "DIGIKEY", "WWW", "HTTP")))


def _shape(tok: str) -> float:
    """How much a token looks like a manufacturer part number: letters and digits mixed, a usable length."""
    letters, digits = sum(c.isalpha() for c in tok), sum(c.isdigit() for c in tok)
    return (1.0 if min(letters, digits) >= 2 else 0.0) + (1.0 if 8 <= len(tok) <= 20 else 0.0) + (0.5 if letters >= 3 else 0.0)


def extract(text: str) -> Extracted:
    up = (text or "").upper()
    ex = Extracted()
    up = up.replace("@", "0")
    ex.dk_pns = digikey_numbers(up)
    ex.dk_pn = ex.dk_pns[0] if ex.dk_pns else None
    ex.dk_guesses = digikey_guesses(up)

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
                    if _TOKEN.fullmatch(tok) and _plausible(tok) and not digikey_numbers(tok):
                        labelled.append(tok)
                    break
    skip = set()
    for line in up.replace("$", "S").splitlines():
        words = line.split()
        for i, w in enumerate(words):
            if re.sub(r"[^A-Z0-9/]", "", w) in NOT_PART:
                skip.update(_clean(x) for x in words[i + 1:i + 3])
    for line in up.replace("$", "S").splitlines():
        toks = [_clean(t) for t in _TOKEN.findall(line)]
        words = line.split()
        for a, b in zip(words, words[1:]):  # "ERA-BAHD 150V": a space inside a part number
            if "-" in a and re.fullmatch(r"\d{2,4}[A-Z]{0,2}", b):
                toks.append(_clean(a + b))
        for tok in toks:
            if _plausible(tok) and tok not in skip and not digikey_numbers(tok):
                seen[tok] += 1
    ex.labelled = list(dict.fromkeys(labelled))
    ex.generic = [t for t in sorted(seen, key=lambda t: -(_shape(t) + min(seen[t], 3))) if t not in ex.labelled and t != ex.lot]
    queries = list(ex.dk_pns[:3])  # (damaged DigiKey numbers are corrected in find_parts, not searched as typed)
    for t in ex.labelled[:2]:
        queries += variants(t)
    queries += ex.generic[:3]
    ex.queries = list(dict.fromkeys(queries))[:8]
    return ex


def _card(p: dict, prefer: str | None = None) -> dict:
    from .enrich import pick_description
    vs = p.get("ProductVariations") or []
    pns = [v["DigiKeyProductNumber"] for v in vs]
    pick = prefer if prefer in pns else (pns[0] if pns else "")  # the packaging on the label, e.g. P15BQCT-ND (cut tape), not just the first
    return {"mpn": p["ManufacturerProductNumber"], "manufacturer": p["Manufacturer"]["Name"],
            "description": pick_description(p)[:140], "photo": p.get("PhotoUrl") or "",
            "dk_pn": pick}


def _many(fn, items, workers=6):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


def find_parts(dk, queries: list[str], dk_pns=None, limit: int = 8, min_score: float = 0.0, guesses=(), fuzz_targets=()) -> list[dict]:
    """DigiKey parts that match what the OCR read, closest first.

    1. DigiKey numbers on the label are looked up exactly; a hit settles it.
    2. Otherwise the part-number guesses are searched, stopping at an exact match.
    3. Only if nothing matched exactly: damaged DigiKey numbers and the likeliest part numbers are retried with look-alike
       characters corrected (8 for B, 0 for Q...), a bounded number of calls."""
    found: dict[tuple, dict] = {}

    def add(p, score, prefer=None):
        c = _card(p, prefer)
        key = (c["mpn"].upper(), c["manufacturer"].upper())
        if key not in found:
            found[key] = {**c, "score": round(score, 3)}
            return
        if prefer and c["dk_pn"] == prefer:  # another route found the same part: keep the packaging the label shows
            found[key]["dk_pn"] = prefer
        found[key]["score"] = max(found[key]["score"], round(score, 3))

    dk_pns = [dk_pns] if isinstance(dk_pns, str) else list(dk_pns or [])
    for pn in dk_pns:
        p = dk.details(pn)
        if p:
            add(p, 1.0, pn)
    if found:
        return list(found.values())[:limit]
    exact = False
    for q in queries:
        if q in dk_pns:
            continue
        for p in dk.search(q, 5):
            s = similarity(p["ManufacturerProductNumber"], q)
            exact = exact or s >= 0.97
            add(p, s)
        if exact:
            break
    if not exact:
        for pn in [*dk_pns, *guesses][:2]:  # a DigiKey number with a damaged character or two
            cands = [f"{b}-ND" for b in fuzz(pn[:-3], 40)]  # exact lookups are cheap and run side by side
            for c, p in zip(cands, _many(dk.details, cands)):
                if p:
                    add(p, similarity(c, pn) * 0.99, c)
        targets = list(dict.fromkeys(fuzz_targets))[:3]
        cands = [(t, v) for t in targets for v in fuzz(t, 8)]
        for (t, v), prods in zip(cands, _many(lambda tv: dk.search(tv[1], 3), cands)):
            for p in prods:
                s = similarity(p["ManufacturerProductNumber"], v)
                if s >= 0.97:
                    add(p, similarity(p["ManufacturerProductNumber"], t))  # ranked by closeness to what was actually read
    return sorted((c for c in found.values() if c["score"] >= min_score), key=lambda c: -c["score"])[:limit]
