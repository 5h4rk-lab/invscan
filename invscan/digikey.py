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

    def lookup(self, mpn: str, sku: str | None = None) -> dict | None:
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
        exact = [p for p in r.json().get("Products", []) if p["ManufacturerProductNumber"].lower() == mpn.lower()]
        if sku:
            exact = [p for p in exact if any(v["DigiKeyProductNumber"].lower() == sku.lower() for v in p.get("ProductVariations", []))] or exact
        if len({p["Manufacturer"]["Name"] for p in exact}) > 1 and not sku:
            self.ambiguous = [f'{p["Manufacturer"]["Name"]}: {p["Description"]["ProductDescription"]}' for p in exact]
            return None
        return exact[0] if exact else None
