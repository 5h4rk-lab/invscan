"""DigiKey Product Information v4 lookup (2-legged OAuth)."""
import os
import time

import requests

API = "https://api.digikey.com"


class DigiKey:
    def __init__(self, client_id=None, client_secret=None):
        self.cid = client_id or os.environ.get("DIGIKEY_CLIENT_ID")
        self.secret = client_secret or os.environ.get("DIGIKEY_CLIENT_SECRET")
        self._tok, self._exp = None, 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.cid and self.secret)

    def _token(self) -> str:
        if self._tok and time.time() < self._exp - 30:
            return self._tok
        r = requests.post(f"{API}/v1/oauth2/token", timeout=20, data={
            "client_id": self.cid, "client_secret": self.secret, "grant_type": "client_credentials"})
        r.raise_for_status()
        d = r.json()
        self._tok, self._exp = d["access_token"], time.time() + d["expires_in"]
        return self._tok

    def _headers(self):
        return {"Authorization": f"Bearer {self._token()}", "X-DIGIKEY-Client-Id": self.cid,
                "X-DIGIKEY-Locale-Site": "US", "X-DIGIKEY-Locale-Language": "en", "X-DIGIKEY-Locale-Currency": "USD"}

    def lookup(self, mpn: str, sku: str | None = None, manufacturer: str | None = None) -> dict | None:
        """The DigiKey product for a scan, or None. Never raises on network trouble.

        An MPN alone is ambiguous (different makers reuse short numbers like '4939'), so a DigiKey
        part number is preferred. Without one, an MPN with several distinct manufacturers is NOT guessed:
        None is returned and the candidates are left in self.ambiguous.
        """
        self.ambiguous = []
        if not self.enabled:
            return None
        try:
            if sku:
                r = requests.get(f"{API}/products/v4/search/{sku}/productdetails", timeout=20, headers=self._headers())
                if r.ok and r.json().get("Product"):
                    return r.json()["Product"]
            r = requests.post(f"{API}/products/v4/search/keyword", timeout=20, json={"Keywords": mpn, "Limit": 10},
                              headers=self._headers())
            r.raise_for_status()
        except requests.RequestException:
            return None
        exact = choose_product(r.json().get("Products", []), mpn, sku, manufacturer, self)
        return exact

    def details(self, pn: str) -> dict | None:
        """The product for an exact DigiKey part number (one call), or None. Never raises on network trouble."""
        if not self.enabled:
            return None
        try:
            r = requests.get(f"{API}/products/v4/search/{pn}/productdetails", timeout=20, headers=self._headers())
            return r.json().get("Product") if r.ok else None
        except (requests.RequestException, ValueError):
            return None

    def search(self, term: str, limit: int = 6) -> list[dict]:
        """Raw DigiKey keyword results for free text (OCR output, a typed search). Never raises on network trouble."""
        if not self.enabled or not (term or "").strip():
            return []
        try:
            r = requests.post(f"{API}/products/v4/search/keyword", timeout=20, json={"Keywords": term.strip(), "Limit": limit},
                              headers=self._headers())
            r.raise_for_status()
        except requests.RequestException:
            return []
        return r.json().get("Products", [])


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def choose_product(products: list[dict], mpn: str, sku: str | None, manufacturer: str | None, holder=None) -> dict | None:
    """Pick the DigiKey product for an exact MPN. Several makers can share an MPN, so a DigiKey PN or a manufacturer
    name (Mouser labels carry one) decides between them; with neither, an ambiguous MPN is not guessed."""
    exact = [p for p in products if p["ManufacturerProductNumber"].lower() == mpn.lower()]
    if sku:
        exact = [p for p in exact if any(v["DigiKeyProductNumber"].lower() == sku.lower() for v in p.get("ProductVariations", []))] or exact
    if manufacturer:
        want = _norm(manufacturer)
        # "Adafruit" matches "Adafruit Industries LLC"; "Texas Instruments" matches "Texas Instruments"
        exact = [p for p in exact if want and (want in _norm(p["Manufacturer"]["Name"]) or _norm(p["Manufacturer"]["Name"]) in want)]
    if len({p["Manufacturer"]["Name"] for p in exact}) > 1 and not sku:
        if holder is not None:
            holder.ambiguous = [f'{p["Manufacturer"]["Name"]}: {p["Description"]["ProductDescription"]}' for p in exact]
        return None
    return exact[0] if exact else None
