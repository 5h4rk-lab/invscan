# invscan

Scan the DataMatrix on a DigiKey parts bag with your phone and it lands in [InvenTree](https://inventree.org):
the part is created and filled in from DigiKey (photo, description, datasheet, specs), the stock is added to the
bin you are standing at, and later you can search for it by name, value, or a note you wrote and see where it is.

It is a small web app that sits next to InvenTree and talks to its API. Nothing is installed inside InvenTree.

## Why

InvenTree's built-in DigiKey barcode plugin identifies a scan, but it needs the supplier part and purchase order to
exist already. Its web UI also refuses phone-sized screens. invscan covers the gap for people who sort a lot of
small bags into drawers.

## Features

- **Scan a bag, get stock.** Reads ECIA / ISO 15434 labels (old and new DigiKey styles). Creates the part, a
  manufacturer part, DigiKey supplier parts, and a stock item with lot, date code and order in its notes.
- **DigiKey enrichment** (optional): description, photo, datasheet link, manufacturer, every packaging variant as a
  supplier part, and the specs as searchable InvenTree parameters. A "Last Scanned" date is kept on each part.
- **Bins.** Type `Cabinet A / Drawer 3 / Bin 2` and the whole location tree is created. Print QR labels at
  `/labels?ids=<location id>`; scan a label to set the current bin, then scan bags into it.
- **No bin label? Write a note.** The bag is parked in an "Unplaced" location with your note ("blue box under the
  desk"). Search finds notes, and the home page lists everything that still needs a home.
- **Print labels from the app.** Bins, parts and stock items, using InvenTree's own label templates. Output goes to
  a label printer registered in InvenTree (for example a Brother QL) or, if none is usable, to a PDF you can open
  or AirPrint. Scanning a bin label printed by InvenTree itself (`INV-SL..`) also works, and scanning an InvenTree
  part or stock label opens that item. "Create bin and print its label" does it in one step.
- **Find it later.** Search by part number, description, specs or your own notes; results show the bin path.
- **Item pages.** Photo, specs, every stock line, edit name/description, move to a bin, link to the InvenTree page.
- **Everything is editable.** Tap any quantity to set the exact number (recorded as a stock count in InvenTree).
- **Safe by default.** Duplicate bags are refused; a PIN is required; wrong PINs are rate limited.

## How it works

```
phone camera -> zxing-wasm (in the browser) -> POST /api/scan -> parse label
                                                              -> DigiKey Product Information API (optional)
                                                              -> InvenTree REST API (part, supplier part, stock)
```

The API token for InvenTree and the DigiKey keys stay on the server; the browser only knows the PIN.

## Quick start (Docker)

You need a running InvenTree (tested with **1.4.1**, API version 511; older versions use a different parameter API).

```bash
git clone https://github.com/5h4rk-lab/invscan.git && cd invscan
cp .env.example .env       # fill in INVENTREE_URL, INVENTREE_TOKEN, SCAN_PIN (and DigiKey keys, optional)
docker compose up -d --build
```

Open <http://localhost:8000>. Browsers only allow camera access on **HTTPS or localhost**, so to use a phone put the
container behind your reverse proxy (Caddy, nginx, Traefik) with a certificate. The photo button works for any
camera app, but live scanning needs HTTPS.

### Without Docker

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
set -a; . ./.env; set +a
uvicorn invscan.server:app --host 0.0.0.0 --port 8000
```

## Deploy on Vercel

The repo is Vercel-ready (`index.py` is the FastAPI entry point, `public/` is served from the CDN).

```bash
npm i -g vercel
vercel link
for k in INVENTREE_URL INVENTREE_TOKEN SCAN_PIN DIGIKEY_CLIENT_ID DIGIKEY_CLIENT_SECRET; do
  vercel env add $k production
done
vercel --prod
```

Your InvenTree must be reachable from the internet for this to work.

## DigiKey keys (optional)

1. Sign in at <https://developer.digikey.com>, create an organization and a production app.
2. Enable **Product Information v4**. The client-credentials flow is enough; the callback URL can be `https://localhost`.
3. Put the Client ID and Secret in `.env`.

## Using it

1. **Home** shows counts, items waiting for a bin, and what you added recently.
2. **Scan**: scan a bin QR (or type a path and press Enter), then scan bags. The result panel at the top tells you
   whether it was added, already in inventory, or failed. For small DataMatrix codes the **photo button** is the
   most reliable path: tap the code to focus, then shoot.
3. **Find**: search; tap a result for the full item page.

## Printing labels

invscan uses InvenTree's label printing API, so whatever printer works in InvenTree works here.

1. Make sure InvenTree has a label printer **machine** (Admin Center > Machines) and that its driver loads. For a
   Brother QL install the `inventree-brother-plugin` package in InvenTree. invscan shows the exact error if
   InvenTree reports the printer as unavailable, and offers a PDF instead.
2. In the app: **Scan > Print label** for the current bin, **Scan > Set bin > Create bin and print its label** for a
   new box, or **Print part label / Print label** on an item page.
3. Choose the template and printer; your choice is remembered on that device.

## What is on a DigiKey label

The 2D code is a DataMatrix in ISO 15434 format 06, fields separated by GS (0x1D):

| Field | Meaning |
|---|---|
| `1P` | Manufacturer part number |
| `30P` | DigiKey part number (newer labels; older labels sometimes put it in `P`) |
| `P` | Customer part / reference |
| `Q` | Quantity |
| `1K`, `10K` | Sales order, invoice |
| `1T`, `9D` | Lot code, date code (newer labels) |
| `4L` | Country of origin |
| `12Z`, `13Z` | DigiKey part/MID id, load id (newer labels print a shared placeholder `999999`) |

Short manufacturer part numbers are **not unique across makers** (`4939` exists from several), so invscan prefers
the DigiKey part number to identify a product and will not guess when the label has none and the MPN is ambiguous.

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `INVENTREE_URL` | yes | InvenTree base URL |
| `INVENTREE_TOKEN` | yes | API token (stays on the server) |
| `SCAN_PIN` | yes | PIN for the web page |
| `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET` | no | Enables DigiKey enrichment |
| `INVSCAN_ALLOW_NO_PIN=1` | no | Run without a PIN (local development only) |

## Security notes

- The app can add stock and change quantities in your InvenTree. Treat the PIN like a password and use a long one
  if the site is public. After 8 wrong PINs from one address the app answers 429 for a minute (per server instance).
- Give the InvenTree token only the access it needs, and serve everything over HTTPS.
- Never commit `.env`.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -q                      # no InvenTree or DigiKey needed
INVSCAN_ALLOW_NO_PIN=1 uvicorn invscan.server:app --reload
```

```
invscan/   parser.py (label -> fields)   ingest.py (scan -> InvenTree)   enrich.py / digikey.py
           params.py  locations.py  notes.py  client.py  server.py (FastAPI)
public/    index.html  app.js  app.css  vendor/ (zxing-wasm)  fonts/
tests/     parser, ingest, PIN gate
```

Third-party assets in `public/` are committed; `scripts/vendor.sh` re-fetches them:
[zxing-wasm](https://github.com/Sec-ant/zxing-wasm) (MIT, wraps Apache-2.0 zxing-cpp),
Bricolage Grotesque and IBM Plex Mono (SIL Open Font License 1.1).

## Limitations

- Built for DigiKey labels. Other suppliers using ECIA labels will parse, but enrichment is DigiKey only.
- Parts are created in an "Unsorted" category; categorise them in InvenTree.
- Live scanning of small DataMatrix codes depends on the camera; the photo button is the fallback.

## License

MIT, see [LICENSE](LICENSE).
