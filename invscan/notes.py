"""Free-text 'where I put it' notes, stored as the first line of a stock item's notes field."""
import re

_LINE = re.compile(r"^NOTE:[ \t]*(.*)\n?", re.M)


def get_note(notes: str | None) -> str:
    m = _LINE.search(notes or "")
    return m.group(1).strip() if m else ""


def set_note(notes: str | None, text: str | None) -> str:
    rest = _LINE.sub("", notes or "", count=1)
    text = (text or "").strip()
    return f"NOTE: {text}\n{rest}" if text else rest
