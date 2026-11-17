"""Mouser: part-number helpers, and an optional Search API client (needs MOUSER_API_KEY)."""
import os
import re

import requests

# Mouser's own part number, e.g. 647-RL81C221MDN1KX (manufacturer prefix, a hyphen, the manufacturer's part number)
MOUSER_PN = re.compile(r"^\d{2,4}-[A-Za-z0-9][^\s]*$")
API = "https://api.mouser.com/api/v1"


def mpn_from_pn(pn: str) -> str:
    """The manufacturer part number is what follows the first hyphen of Mouser's part number."""
    return pn.split("-", 1)[1] if "-" in pn else pn


def to_product(part: dict) -> dict:
    """A Mouser search hit in the same shape as a DigiKey product, so enrichment can treat them alike."""
    pn = part.get("MouserPartNumber", "")
    return {
        "ManufacturerProductNumber": part.get("ManufacturerPartNumber") or mpn_from_pn(pn),
        "Manufacturer": {"Name": part.get("Manufacturer", "")},
        "Description": {"ProductDescription": part.get("Description", "")},
        "PhotoUrl": part.get("ImagePath", ""),
        "DatasheetUrl": part.get("DataSheetUrl", ""),
        "ProductUrl": part.get("ProductDetailUrl", ""),
        "Category": {"Name": part.get("Category", "")},
        "Parameters": [{"ParameterText": a.get("AttributeName", ""), "ValueText": a.get("AttributeValue", "")}
                       for a in part.get("ProductAttributes", []) if a.get("AttributeName")],
        "ProductVariations": [{"DigiKeyProductNumber": pn, "PackageType": {"Name": ""}}] if pn else [],
    }


class Mouser:
    def __init__(self, key: str | None = None):
        self.key = key or os.environ.get("MOUSER_API_KEY")
        self.rejected = False  # Mouser said the key is not valid: stop asking

    @property
    def enabled(self) -> bool:
        return bool(self.key) and not self.rejected

    @property
    def status(self) -> str:
        """unset | unchecked | ok | rejected: for the health endpoint."""
        if not self.key:
            return "unset"
        return "rejected" if self.rejected else getattr(self, "_ok", False) and "ok" or "unchecked"

    def lookup(self, pn: str) -> dict | None:
        """Mouser's details for a Mouser part number, or None. Never raises on network trouble."""
        if not self.enabled:
            return None
        try:
            r = requests.post(f"{API}/search/partnumber", params={"apiKey": self.key}, timeout=20,
                              json={"SearchByPartRequest": {"mouserPartNumber": pn, "partSearchOptions": "Exact"}})
            r.raise_for_status()
            body = r.json()
        except (requests.RequestException, ValueError):
            return None
        if any(e.get("PropertyName") == "API Key" for e in body.get("Errors") or []):
            self.rejected = True  # wrong key type, mistyped, or not activated yet
            return None
        self._ok = True
        parts = (body.get("SearchResults") or {}).get("Parts") or []
        hit = next((p for p in parts if p.get("MouserPartNumber", "").lower() == pn.lower()), None)
        return to_product(hit) if hit else None
