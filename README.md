# invscan

Scan the DataMatrix on a DigiKey or Mouser parts bag with your phone and it lands in [InvenTree](https://inventree.org):
the part is created and filled in from DigiKey (photo, description, datasheet, specs), the stock is added to the
bin you are standing at, and later you can search for it by name, value, or a note you wrote and see where it is.

It is a small web app that sits next to InvenTree and talks to its API. Nothing is installed inside InvenTree.

## Why

InvenTree's built-in DigiKey barcode plugin identifies a scan, but it needs the supplier part and purchase order to
exist already. Its web UI also refuses phone-sized screens. invscan covers the gap for people who sort a lot of
small bags into drawers.

## Features

- **Scan a bag, get stock.** Reads ECIA / ISO 15434 labels: DigiKey (old and new styles) and Mouser. Creates the part, a
  manufacturer part, DigiKey supplier parts, and a stock item with lot, date code and order in its notes.
- **DigiKey enrichment** (optional): description, photo, datasheet link, manufacturer, every packaging variant as a
  supplier part, and the specs as searchable InvenTree parameters. A "Last Scanned" date is kept on each part.
- **Bins.** Enter Room number, Cabinet, Drawer and Bin (or type `Room 204 / Cabinet A / Drawer 3 / Bin 2`) and the whole location tree is created. "Add room" moves an existing cabinet into a room. Print QR labels at
  `/labels?ids=<location id>`; scan a label to set the current bin, then scan bags into it.
- **No bin label? Write a note.** The bag is parked in an "Unplaced" location with your note ("blue box under the
  desk"). Search finds notes, and the home page lists everything that still needs a home.
- **Print labels from the app.** Bins, parts and stock items, using InvenTree's own label templates. Output goes to
  a label printer registered in InvenTree (for example a Brother QL) or, if none is usable, to a PDF you can open
  or AirPrint. Scanning a bin label printed by InvenTree itself (`INV-SL..`) also works, and scanning an InvenTree
  part or stock label opens that item. "Create bin and print its label" does it in one step.
- **Add parts that have no DigiKey label.** "Add a part by hand": type a name or a part number (a DigiKey number such as
  `296-19733-5-ND` fills in the details), a quantity, and optionally take a photo. The photo becomes the part's picture
  in search results. Then print a label with a QR that opens the item when scanned.
- **Categories like DigiKey's.** New parts are filed in DigiKey's own category tree (for example
  `Capacitors / Aluminum - Polymer Capacitors`). **Find > Browse by category** drills down with counts, and each
  category has search, sorting and DigiKey-style **filters** built from the part's specs (Capacitance, Voltage,
  Package and so on). **Sort them** files existing Unsorted parts the same way, and parts with no supplier record at all (a laptop, a
  hand-made board) go to **Miscellaneous**, which is also the default for parts you add by hand, and Edit lets you change a part's
  category by hand.
- **McMaster-style browsing.** On a computer the category tree is a sidebar that expands in place, and **hovering**
  a part shows its photo, specs and where it is stored, while hovering a category shows its sub-categories and some
  of its parts. On a phone the same tree expands inline, and tapping a part's picture opens the same preview.
- **Spots duplicates of what you already hold.** Scan a bag of a part you already have and the result says
  "You already have this part", shows where, and has **Put this bag there**. With no bin set, the note sheet offers
  the place you already keep it.
- **Worn or covered labels.** If the square code cannot be read (a torn, peeled or covered code is unreadable to any
  scanner), type the DigiKey part number printed after `PN:`; the part, specs, category and supplier part are filled
  in from DigiKey, and lot and date codes can be added.
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
   The printer's IP address must be reachable **from the InvenTree server** (not from your phone or from invscan).
   If a print never finishes, check Admin Center > Background Tasks for a failed `print_labels` task: a connection
   timeout there means InvenTree cannot reach the printer. Plugins installed through InvenTree's UI can disappear
   when its container is recreated; to keep one, list it in InvenTree's `plugins.txt` (in its data volume).
2. In the app: **Scan > Print label** for the current bin, **Scan > Set bin > Create bin and print its label** for a
   new box, or **Print part label / Print label** on an item page.
3. Choose the template and printer; your choice is remembered on that device.

### Part and stock labels

`invscan_stock_label.html` (quantity and place) and `invscan_part_label.html` are 62 x 30 mm labels with a QR that
opens the item in invscan when scanned, so any part without a DigiKey code can still be scanned later. Each label
carries a small mark in the corner: a picture per InvenTree owner if `label_templates/marks/owner_<NAME>.png` exists
(for example `owner_EV.png` for the user `EV`; these are local files and not committed), otherwise the default hen
(`scripts/make_hen.py`). Run `scripts/install_labels.py` to install all three designs.

### Bin label design

`label_templates/invscan_bin_label.html` is a 62 x 30 mm label (QR on the left, the whole place stacked on the
right: room, cabinet, drawer, with the bin name large). Install it into InvenTree once; re-run to update it:

```bash
set -a; . ./.env; set +a
python scripts/install_labels.py
```

The room is shown in its own highlighted block: any level whose name starts with "Room" (for example `Room 204`). It is picked automatically as the default bin label. When creating a bin, fill in Room number (typing `204` saves `Room 204`), Cabinet or shelf,
Drawer and Bin or box; the path becomes the location tree, so the label shows each level. The name steps down in size (and wraps for very long names) so it is never cut off, and the corner mark
(hen, or a per-owner picture) sits top-right. Adjust the HTML for other media sizes (the template reads
InvenTree's `width` and `height`).

## Categories and filters

Categories come from the DigiKey product record, which carries the full path, and are created in InvenTree as needed.
A part you filed yourself is never moved. The filters are computed from the parts' specs, stored as InvenTree
parameters: a filter appears once several parts in a category share a spec, values inside one filter are OR and
different filters are AND, and each filter's counts ignore its own selection so you can switch values freely.
InvenTree cannot return parts together with their parameters, so the app reads all parameters and keeps them for 30
seconds. That is fast for thousands of parts; for a very large inventory a cache closer to InvenTree would help.

## Mouser labels

Mouser's square code carries the purchase order, line item, your customer part number, quantity, invoice, country
of origin and the manufacturer name, but **not the part number**. That is only in the long `P/N:` barcode on the
same label (for example `647-RL81C221MDN1KX`; the manufacturer part number is what follows the first hyphen). So
invscan reads both: in a photo (or the live camera) it pairs the square code with the closest `P/N:` barcode, and
if that barcode is not in view it asks you to type the number. The manufacturer name on the label is used to pick
the right product when several makers share a part number.

Details (description, photo, specs) come from Mouser's Search API when `MOUSER_API_KEY` is set (get a key from the
API section of your Mouser account), otherwise from DigiKey by manufacturer part number. Either way a Mouser supplier
part with Mouser's own SKU is created. A bag is refused as a duplicate by (invoice, line item, PO).

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
| `MOUSER_API_KEY` | no | Mouser Search API key: Mouser's own details for Mouser bags |
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

- Built for DigiKey and Mouser labels. Other suppliers using ECIA labels may parse, but get no enrichment.
- `/api/health` reports `mouser_key` as `unset`, `unchecked`, `ok` or `rejected`. A rejected key (wrong key type, mistyped, or not yet activated) is noticed on the first lookup and not retried; Mouser bags then use DigiKey data.
- Parts are created in an "Unsorted" category; categorise them in InvenTree.
- Text recognition (OCR) of printed labels was tried and is not reliable enough to trust: it confuses `I`/`1`, `S`/`5`, `C`/`0`. Type the part number instead.
- Live scanning of small DataMatrix codes depends on the camera; the photo button is the fallback.

## License

MIT, see [LICENSE](LICENSE).
