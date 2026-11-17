ZXingWASM.setZXingModuleOverrides({ locateFile: p => "/static/vendor/" + p });
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { pin: localStorage.pin || "", bin: JSON.parse(localStorage.bin || "null"), view: "", cam: null, paused: false, last: "", lastT: 0, lastSeen: 0, busy: false, firstHome: true, open: new Set(JSON.parse(localStorage.treeOpen || "[]")), hoverEl: null, cats: [], cat: { id: null, q: "", sort: "relevance", f: {} } };

/* ---------- api ---------- */
function setPin(p) {
  state.pin = p; localStorage.pin = p;
  document.cookie = "pin=" + encodeURIComponent(p) + ";path=/;max-age=31536000;SameSite=Strict;Secure";
}
function askPin() {
  return new Promise(res => openSheet(`<h3>Enter your PIN</h3><p class="muted sm">Needed once per device.</p>
    <input class="field" name="pin" type="password" autocomplete="current-password" required autofocus>
    <button class="btn primary" type="submit">Unlock</button>`, f => { res(f.get("pin")); }, () => res(null)));
}
async function api(path, body, retry = true) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json", "X-Pin": state.pin }, body: JSON.stringify(body) } : { headers: { "X-Pin": state.pin } });
  if (r.status === 401 && retry) { const p = await askPin(); if (p) { setPin(p); return api(path, body, false); } }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Request failed (" + r.status + ")");
  return j;
}
const img = (u, n) => u ? `<img class="thumb" src="${esc(u)}" alt="" loading="lazy">` : `<div class="thumb empty">${esc((n || "?").slice(0, 3))}</div>`;
const tag = (path, unplaced) => `<span class="tag${unplaced ? " warn" : ""}" title="${esc(path)}">${esc(path).split("/").map(s => s.replace(/ /g, "&nbsp;")).join("/&#8203;")}</span>`;  // lines break only after a slash
const safeUrl = u => /^https?:\/\//i.test(u || "") ? u : "";
const plink = (id, html, cls = "") => `<a class="${cls}" href="#part/${id}">${html}</a>`;
const CHECK = '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>', WARN = '<svg viewBox="0 0 24 24"><path d="M12 7v6M12 17h.01"/></svg>', CROSS = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';
function toast(t) { const d = document.createElement("div"); d.className = "toast"; d.textContent = t; document.body.append(d); setTimeout(() => d.remove(), 2400); }

/* ---------- sheet ---------- */
function openSheet(html, onSubmit, onCancel, cancelText = "Cancel") {
  const d = $("#sheet"), f = $("#sheetForm");
  f.innerHTML = html + `<button class="btn quiet" type="button" data-x>${cancelText}</button>`;
  let done = false;
  f.onsubmit = async e => { e.preventDefault(); if (done) return; const fd = new FormData(f); done = true; d.close(); await onSubmit?.(fd); };
  f.querySelector("[data-x]").onclick = () => d.close();
  d.onclose = () => { if (!done) onCancel?.(); state.paused = false; state.lastSeen = Date.now(); };
  state.paused = true; d.showModal();
}

/* ---------- editable quantity ---------- */
const qbtn = (id, name, v) => `<button class="qbtn" type="button" data-qty data-id="${id}" data-name="${esc(name)}" data-val="${esc(v)}" aria-label="Edit quantity of ${esc(name)}">${esc(v)}</button>`;
function qtySheet(id, name, val, after) {
  openSheet(`<h3>How many <span class="mono">${esc(name)}</span>?</h3>
   <p class="muted sm">Set the exact number on hand. The change is kept in the item's history.</p>
   <div class="stepper"><button class="btn" type="button" data-d="-1" aria-label="One less">-</button>
    <input class="field mono" name="qty" type="number" inputmode="decimal" min="0" step="any" value="${esc(val)}" required autofocus>
    <button class="btn" type="button" data-d="1" aria-label="One more">+</button></div>
   <button class="btn primary" type="submit">Save quantity</button>`,
    async f => {
      try { const r = await api(`/api/stock/${id}/qty`, { qty: +f.get("qty") }); toast(`${name}: ${r.qty}`); after ? after(r) : refresh(); }
      catch (e) { toast(e.message); }
    });
  const i = $("#sheetForm input[name=qty]");
  $("#sheetForm").querySelectorAll("[data-d]").forEach(b => b.onclick = () => { i.value = Math.max(0, (+i.value || 0) + +b.dataset.d); });
  i.select();
}
function refresh() { state.view === "find" ? runFind() : state.view === "home" ? loadHome() : state.view === "part" ? loadPart(state.partId) : state.view === "cat" ? loadCat(state.catId) : 0; }
document.addEventListener("click", e => {
  const b = e.target.closest("[data-qty]"); if (!b) return;
  qtySheet(+b.dataset.id, b.dataset.name, b.dataset.val, b.dataset.after ? r => { b.textContent = r.qty; b.dataset.val = r.qty; } : null);
});

/* ---------- photos ---------- */
async function shrinkPhoto(file, max = 1600) {
  const bm = await createImageBitmap(file), k = Math.min(1, max / Math.max(bm.width, bm.height));
  const c = document.createElement("canvas"); c.width = Math.round(bm.width * k); c.height = Math.round(bm.height * k);
  c.getContext("2d").drawImage(bm, 0, 0, c.width, c.height);
  return new Promise(r => c.toBlob(r, "image/jpeg", 0.82));
}
async function uploadPhoto(partId, file) {
  const blob = await shrinkPhoto(file);
  const r = await fetch(`/api/part/${partId}/image`, { method: "POST", headers: { "X-Pin": state.pin, "Content-Type": "image/jpeg" }, body: blob });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Photo upload failed (" + r.status + ")");
  return j;
}

/* ---------- add by hand ---------- */
function handSheet(prefill = "") {
  openSheet(`<h3>Add a part by hand</h3>
   <p class="muted sm">For parts with no DigiKey label. Type a name or part number. A DigiKey number such as 296-19733-5-ND fills in the details for you.</p>
   <label>Part number or name<input class="field" name="name" value="${esc(prefill)}" placeholder="Blue relay module" required autocomplete="off"></label>
   <label>Description (optional)<input class="field" name="description" placeholder="5V 1-channel, from the bench drawer" autocomplete="off"></label>
   <label>Quantity<input class="field" name="qty" type="number" inputmode="numeric" min="1" required placeholder="1"></label>
   <div class="photo-pick"><button class="btn sm" type="button" id="pickPhoto">Take or choose a photo</button><span id="photoName">So it shows up when you search</span></div>
   <input name="photo" id="photoIn" type="file" accept="image/*" capture="environment" hidden>
   ${state.bin ? `<div>${tag(state.bin.path)}</div>` : `<label>Where is it?<textarea class="field" name="note" required placeholder="Blue box under the desk, left side"></textarea></label>`}
   <button class="btn primary" type="submit">Add part</button>`,
    async f => {
      const body = { name: f.get("name").trim(), description: (f.get("description") || "").trim(), qty: +f.get("qty"), location_id: state.bin?.id ?? null, note: (f.get("note") || "").trim() || null };
      let r;
      try { r = await api("/api/part/new", body); } catch (e) { toast(e.message); return; }
      const photo = f.get("photo");
      if (photo && photo.size) {
        try { const u = await uploadPhoto(r.part_id, photo); r.thumbnail = u.thumbnail || r.thumbnail; }
        catch (e) { toast("Added, but the photo failed: " + e.message); }
      }
      state.view === "scan" || (location.hash = "#scan");
      showResult("ok", r.new_part ? "Added to inventory (new part)" : "Added to inventory", r, r.message ? esc(r.message) : "");
      card("", `<div class="name">${esc(r.name)}</div><div class="sm muted">Added ${esc(r.qty)} to ${esc(r.path || "")}</div>`, r.thumbnail);
      if (r.stock_id) setTimeout(() => printSheet("stockitem", [r.stock_id], r.name), 150);  // a part added by hand has no label yet
    });
  $("#pickPhoto").onclick = () => $("#photoIn").click();
  $("#photoIn").onchange = e => { $("#photoName").textContent = e.target.files[0] ? "Photo ready: " + e.target.files[0].name : "So it shows up when you search"; };
}
$("#handBtn").onclick = () => handSheet();

/* ---------- printing ---------- */
async function printSheet(model, ids, title) {
  let info;
  try { info = await api("/api/printing"); } catch (e) { toast(e.message); return; }
  const tpls = info.templates[model] || [], saved = JSON.parse(localStorage.printPrefs || "{}");
  if (!tpls.length) { toast("InvenTree has no enabled label template for this. Add one in InvenTree."); return; }
  const up = info.printers.filter(p => p.ok), down = info.printers.filter(p => !p.ok);
  const outDefault = up.find(p => p.id === saved.machine)?.id || up[0]?.id || "pdf";
  const tplDefault = tpls.find(x => x.id === saved[model])?.id || (tpls.find(x => /^invscan/i.test(x.name)) || tpls.find(x => x.name.includes("QR + Text")) || tpls[0]).id;
  const kind = { stocklocation: "bin label", stockitem: "item label", part: "part label" }[model] || "label";
  openSheet(`<h3>Print ${kind}</h3><p class="muted sm">${esc(title)}</p>
    <label>Label<select class="field" name="template">${tpls.map(x => `<option value="${x.id}" ${x.id === tplDefault ? "selected" : ""}>${esc(/\d+x\d+/.test(x.name) ? x.name : x.name + " (" + x.size + ")")}</option>`).join("")}</select></label>
    <label>Send to<select class="field" name="out">${up.map(p => `<option value="${esc(p.id)}" ${p.id === outDefault ? "selected" : ""}>${esc(p.name)}</option>`).join("")}<option value="pdf" ${outDefault === "pdf" ? "selected" : ""}>PDF to open or AirPrint</option></select></label>
    ${down.length ? `<div class="note">${down.map(p => `${esc(p.name)} is not available in InvenTree: ${esc(p.error || "inactive")}.`).join("<br>")}</div>` : ""}
    <button class="btn primary" type="submit">Print</button>`,
    async f => {
      const out = f.get("out"), template = +f.get("template");
      localStorage.printPrefs = JSON.stringify({ ...saved, [model]: template, machine: out === "pdf" ? saved.machine : out });
      toast("Preparing label...");
      try {
        const r = await api("/api/print", { model, ids, template, machine: out === "pdf" ? null : out });
        if (!r.ok) { openSheet(`<h3>Could not print</h3><p class="sm">${esc(r.message)}</p>`, null, null, "Close"); return; }
        if (r.mode === "printer") toast(r.message);
        else openSheet(`<h3>Label ready</h3>${r.message && r.message !== "PDF ready." ? `<p class="note">${esc(r.message)}</p>` : ""}
          <a class="btn primary" href="${esc(r.url)}" target="_blank" rel="noopener">Open label PDF</a>`, null, null, "Close");
      } catch (e) { toast(e.message); }
    });
}

/* ---------- bin ---------- */
function renderBin() {
  const b = $("#binbar");
  if (state.bin) {
    b.className = "binbar on";
    b.innerHTML = `<div class="binhead"><small>Putting bags in</small>${tag(state.bin.path)}</div>
      <div class="binacts">${hasRoom(state.bin.path) ? "" : '<button class="btn sm" data-room>Add room</button>'}<button class="btn sm" data-print>Print bin label</button><button class="btn sm" data-bin>Change</button></div>`;
  } else {
    b.className = "binbar note";
    b.innerHTML = `<div class="binhead"><b>No bin set</b><small>Scan a bin label, or write a note about where each bag goes.</small></div>
      <div class="binacts"><button class="btn sm primary" data-bin>Set bin</button></div>`;
  }
  b.querySelector("[data-bin]").onclick = binSheet;
  const rb = b.querySelector("[data-room]"); if (rb) rb.onclick = roomSheet;
  const pb = b.querySelector("[data-print]"); if (pb) pb.onclick = () => printSheet("stocklocation", [state.bin.id], state.bin.path);
}
function setBin(b) { state.bin = b; localStorage.bin = JSON.stringify(b); renderBin(); }
const BIN_FIELDS = [["room", "Room number", "204"], ["cabinet", "Cabinet or shelf", "Cabinet A"], ["drawer", "Drawer", "Drawer 3"], ["bin", "Bin or box", "Bin 2"]];
function binBody(f) {
  const path = (f.get("path") || "").trim();
  if (path) return { path };
  const b = {}; BIN_FIELDS.forEach(([k]) => { b[k] = (f.get(k) || "").trim(); });
  return Object.values(b).some(Boolean) ? b : null;
}
const hasRoom = p => (p || "").split("/").some(s => s.trim().toLowerCase().startsWith("room"));
function binSheet() {
  const last = JSON.parse(localStorage.binParts || "{}");
  openSheet(`<h3>Where are bags going?</h3>
   <p class="muted sm">Point the camera at a bin label, or fill in the place. Anything new is created, and you can print its label.</p>
   <div class="roomsec"><label>Room number<input class="field" name="room" inputmode="text" placeholder="204" value="${esc(last.room || "")}" autocomplete="off"></label>
    <span class="sm muted">Typing 204 saves it as Room 204 and prints it in a highlighted block on the label.</span></div>
   <label>Cabinet or shelf<input class="field" name="cabinet" placeholder="Cabinet A" value="${esc(last.cabinet || "")}" autocomplete="off"></label>
   <div class="grid2"><label>Drawer<input class="field" name="drawer" placeholder="Drawer 3" autocomplete="off"></label><label>Bin or box<input class="field" name="bin" placeholder="Bin 2" autocomplete="off"></label></div>
   <details><summary class="sm muted" style="cursor:pointer">Type a full path instead</summary><input class="field mono" name="path" placeholder="Room 204 / Cabinet A / Drawer 3 / Bin 2" style="margin-top:8px"></details>
   <button class="btn primary" type="submit">Use this bin</button>
   <button class="btn" type="button" id="mkprint">Create bin and print its label</button>
   <button class="btn" type="button" id="nobin">No bin label: I'll write a note instead</button>`,
    async f => { const body = binBody(f); if (body) { rememberBin(f); try { setBin(await api("/api/bin", body)); } catch (e) { toast(e.message); } } });
  $("#nobin").onclick = () => { setBin(null); $("#sheet").close(); };
  $("#mkprint").onclick = async () => {
    const f = new FormData($("#sheetForm")), body = binBody(f); if (!body) { toast("Fill in at least the bin or box"); return; }
    rememberBin(f);
    try { const b = await api("/api/bin", body); setBin(b); $("#sheet").close(); setTimeout(() => printSheet("stocklocation", [b.id], b.path), 80); } catch (e) { toast(e.message); }
  };
}
function rememberBin(f) { localStorage.binParts = JSON.stringify({ room: (f.get("room") || "").trim(), cabinet: (f.get("cabinet") || "").trim() }); }
function roomSheet() {
  const last = JSON.parse(localStorage.binParts || "{}");
  openSheet(`<h3>Add a room</h3>
   <p class="muted sm">${tag(state.bin.path)}</p>
   <p class="sm">The top level of this place and everything inside it moves into the room. Other bins in the same cabinet get the room too.</p>
   <label>Room number<input class="field" name="room" placeholder="204" value="${esc(last.room || "")}" required autofocus autocomplete="off"></label>
   <button class="btn primary" type="submit">Put in this room</button>`,
    async f => { try { const r = await api(`/api/bin/${state.bin.id}/room`, { room: f.get("room") }); setBin(r); toast("Now in " + r.path); } catch (e) { toast(e.message); } });
}

/* ---------- scanning ---------- */
function card(cls, html, thumb) {
  const d = document.createElement("div"); d.className = "fc " + cls;
  d.innerHTML = (thumb ? img(thumb) : "") + `<div class="body">${html}</div>`;
  $("#feed").prepend(d); navigator.vibrate?.(cls ? [70, 50, 70] : 50);
}
function showResult(kind, title, r, extra = "") {
  const box = $("#result"), cls = kind === "ok" ? "" : kind;
  box.className = "result " + cls; box.hidden = false;
  box.innerHTML = `<div class="bar">${kind === "ok" ? CHECK : kind === "dup" ? WARN : CROSS}<span>${esc(title)}</span><button class="x" type="button" aria-label="Dismiss" id="resX">&times;</button></div>
   <div class="inner">${r.part_id ? plink(r.part_id, img(r.thumbnail, r.name), "thumb-link") : ""}
    <div class="body">${r.part_id ? plink(r.part_id, esc(r.name || r.mpn), "nm") : `<span class="mono">${esc(r.mpn || "")}</span>`}
     ${r.description ? `<div class="sm muted">${esc(r.description)}</div>` : ""}
     ${r.stock_id ? `<div class="rline">${tag(r.path || "No location", r.path === "Unplaced")}</div><div class="rline"><span class="sm muted">Quantity</span>${qbtn(r.stock_id, r.name || r.mpn, r.qty).replace("data-qty", 'data-qty data-after="1"')}</div>` : ""}
     ${r.note ? `<div class="note">${esc(r.note)}</div>` : ""}${extra ? `<div class="sm">${extra}</div>` : ""}
     ${r.part_id ? `<div class="acts">${plink(r.part_id, "Open item", "btn sm")}${r.stock_id ? '<button class="btn sm primary" type="button" id="resPrint">Print item label</button>' : ""}</div>` : ""}</div></div>`;
  $("#resX").onclick = () => { box.hidden = true; };
  const rp = $("#resPrint"); if (rp) rp.onclick = () => printSheet("stockitem", [r.stock_id], r.name || r.mpn);
  const f = $("#finder"); f.classList.remove("f-ok", "f-dup", "f-err"); f.classList.add("f-" + kind); setTimeout(() => f.classList.remove("f-" + kind), 1200);
  window.scrollTo({ top: 0, behavior: "smooth" });
}
async function sendBag(raw, note, extra = {}) {
  state.busy = true;
  try {
    const r = await api("/api/scan", { raw, location_id: state.bin?.id ?? null, qty: +$("#qty").value || null, note: note || null, mouser_pn: extra.mouser_pn || null });
    if (r.kind === "need_pn") { state.busy = false; return mouserSheet(raw, note); }
    if (r.kind === "part") { location.hash = "#part/" + r.part_id; }
    else if (r.kind === "bin") { setBin(r); card("", `<div>Bin set</div>${tag(r.path)}`); toast("Bin set"); }
    else if (r.status === "created") {
      showResult("ok", r.new_part ? "Added to inventory (new part)" : "Added to inventory", r, r.message ? esc(r.message) : "");
      card("", `<div class="name">${esc(r.name)}</div><div class="sm muted">Added ${esc(r.qty)} to ${esc(r.path || "")}</div>`, r.thumbnail);
    } else if (r.status === "duplicate") {
      showResult("dup", "Already in inventory. Nothing added.", r);
      card("dup", `<div class="name">${esc(r.name || r.mpn)}</div><div class="sm">Already scanned in.</div>`, r.thumbnail);
    } else { showResult("err", "Not added", { mpn: r.mpn }, esc(r.message)); card("err", `<div class="name">${esc(r.mpn)}</div><div class="sm">${esc(r.message)}</div>`); }
  } catch (e) { showResult("err", "Not added", { mpn: "" }, esc(e.message)); card("err", `<div class="sm">${esc(e.message)}</div>`); }
  state.busy = false;
}
function mouserSheet(raw, note) {
  openSheet(`<h3>Mouser part number</h3>
    <p class="muted sm">Mouser's square code does not include the part number. Type the one printed after <b>P/N:</b> on the label, for example <span class="mono">647-RL81C221MDN1KX</span>. In a photo, include the long P/N barcode and it is read for you.</p>
    <input class="field mono" name="pn" placeholder="647-RL81C221MDN1KX" required autocomplete="off" autocapitalize="characters" autofocus>
    <button class="btn primary" type="submit">Add to inventory</button>`,
    f => sendBag(raw, note, { mouser_pn: f.get("pn").trim() }));
}
function handleCode(text, extra = {}) {
  const now = Date.now();
  if (state.busy || state.paused) return;
  state.last = text; state.lastT = now;
  $("#finder").classList.add("hit"); setTimeout(() => $("#finder").classList.remove("hit"), 400);
  const isBag = /^\[\)>|\x1d|\u241d/.test(text);
  if (!isBag || state.bin) return sendBag(text, null, extra);
  // bag without a bin: ask where it is going so it can be found later
  const mpn = (text.match(/1P([^\x1d␝]+)/) || [])[1] || "this bag";
  openSheet(`<h3>Where is it going?</h3>
    <p class="muted sm"><span class="mono">${esc(mpn)}</span> has no bin. Write where you put it and you can search for these words later.</p>
    <textarea class="field" name="note" placeholder="Blue box under the desk, left side" required autofocus></textarea>
    <button class="btn primary" type="submit">Save with note</button>
    <button class="btn" type="button" id="setbin">Set a bin instead</button>`,
    f => sendBag(text, f.get("note").trim(), extra));
  $("#setbin").onclick = () => { $("#sheet").close(); setTimeout(binSheet, 60); };
}
// A Mouser square code has no part number: it is in the long "P/N:" barcode on the same label.
const isMouserCode = s => /(\x1d|<GS>|\u241d)14K\d/.test(s) && !/(\x1d|<GS>|\u241d)1P/.test(s);
async function readImage(src, w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; const x = c.getContext("2d", { willReadFrequently: true });
  draw(x); const data = x.getImageData(0, 0, w, h);
  const rs = await ZXingWASM.readBarcodes(data, { formats: ["DataMatrix", "QRCode"], tryHarder: true, maxNumberOfSymbols: 3 });
  const main = rs.find(r => r.format === "DataMatrix") || rs[0];
  if (!main) return null;
  const out = { text: main.text };
  if (isMouserCode(main.text)) {
    out.needsPn = true;
    const lin = await ZXingWASM.readBarcodes(data, { formats: ["Code128"], tryHarder: true, maxNumberOfSymbols: 16 });
    const mid = p => ({ x: (p.topLeft.x + p.bottomRight.x) / 2, y: (p.topLeft.y + p.bottomRight.y) / 2 }), me = mid(main.position);
    // other bags in the photo have P/N barcodes too, so take the one closest to this label's square code
    const best = lin.filter(r => /^\d{2,4}-\S+$/.test(r.text))
      .map(r => ({ r, d: Math.hypot(mid(r.position).x - me.x, mid(r.position).y - me.y) })).sort((a, b) => a.d - b.d)[0];
    if (best) out.mouser_pn = best.r.text;
  }
  return out;
}
async function startCam() {
  if (state.cam) return;
  const off = $("#camOff"), v = $("#v");
  try {
    const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 3840 }, height: { ideal: 2160 } } });
    state.cam = s; v.srcObject = s; await v.play(); off.hidden = true;
  } catch (e) { off.hidden = false; off.textContent = "Camera unavailable (" + e.message + "). Use the photo button."; $("#st").hidden = true; return; }
  let frames = 0;
  (async function loop() {
    if (!state.cam) return;
    if (!state.paused && !state.busy && v.videoWidth) {
      try {
        const t = await readImage(v, v.videoWidth, v.videoHeight, x => x.drawImage(v, 0, 0));
        frames++; $("#st").textContent = `${v.videoWidth}x${v.videoHeight} - frame ${frames}`;
        if (t && t.needsPn && !t.mouser_pn) {
          $("#st").textContent = "Mouser label: show the long P/N barcode too";
        } else if (t) {
          // same code still in view: wait until it has been out of frame ~2.5s before reacting again
          const seen = Date.now(), same = t.text === state.last && seen - state.lastSeen < 2500;
          state.lastSeen = seen;
          if (!same) handleCode(t.text, { mouser_pn: t.mouser_pn });
        }
      } catch { /* keep trying */ }
    }
    setTimeout(loop, 160);
  })();
}
function stopCam() { state.cam?.getTracks().forEach(t => t.stop()); state.cam = null; }
$("#photoBtn").onclick = () => $("#photo").click();
$("#photo").onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const bm = await createImageBitmap(f), k = Math.min(1, 3000 / Math.max(bm.width, bm.height)), w = Math.round(bm.width * k), h = Math.round(bm.height * k);
    const t = await readImage(bm, w, h, x => x.drawImage(bm, 0, 0, w, h));
    state.last = "";
    if (t) handleCode(t.text, { mouser_pn: t.mouser_pn }); else showResult("err", "No code found in the photo", { mpn: "" }, `${bm.width}x${bm.height}. Move closer, keep the label flat, and avoid glare.`);
  } catch (x) { card("err", `<div class="sm">${esc(x.message)}</div>`); }
  e.target.value = "";
};

/* ---------- home ---------- */
function stockRow(s, extra = "") {
  return `<div class="row" data-peek="${s.part_id}">${plink(s.part_id, img(s.thumbnail, s.name), "thumb-link")}<div class="body"><div class="name">${plink(s.part_id, esc(s.name), "nm")}</div>
    ${s.description ? `<div class="desc">${esc(s.description)}</div>` : ""}
    <div class="meta">${tag(s.path, s.unplaced)}</div>${s.note ? `<div class="note">${esc(s.note)}</div>` : ""}</div>
    <div class="qty">${qbtn(s.stock_id, s.name, s.qty)}${extra}</div></div>`;
}
async function loadHome() {
  $("#homeBody").innerHTML = `<h2>Loading</h2><div class="list">${'<div class="row"><div class="thumb empty sk"></div><div class="body"><div class="sk" style="width:60%"></div><div class="sk" style="width:85%;margin-top:8px"></div></div></div>'.repeat(3)}</div>`;
  try {
    const h = await api("/api/home");
    $("#stats").innerHTML = `<div><b>${h.counts.parts}</b><span>parts</span></div><div><b>${h.counts.stock}</b><span>stock lines</span></div><div><b>${h.counts.bins}</b><span>bins</span></div>` + (h.unsorted ? `<a href="#find" style="color:inherit;text-decoration:none"><b>${h.unsorted}</b><span>to sort</span></a>` : "");
    let out = "";
    out += `<h2>Needs a home <small>${h.unplaced.length ? h.unplaced.length + " waiting" : ""}</small></h2>`;
    out += h.unplaced.length
      ? `<div class="list">${h.unplaced.map(s => `<div data-s="${s.stock_id}" data-n="${esc(s.name)}" data-note="${esc(s.note)}">${stockRow(s, '')}<div style="padding:0 16px 14px"><button class="btn sm" data-place>Put in a bin</button></div></div>`).join("")}</div>`
      : `<div class="list"><div class="empty-state">Everything has a bin. Scan a bag without a bin and write a note, and it shows up here.</div></div>`;
    out += `<h2>Recently added</h2>`;
    out += h.recent.length ? `<div class="list stagger">${h.recent.map((s, i) => `<div style="--i:${i}">${stockRow(s, `<small>${esc(s.date)}</small>`)}</div>`).join("")}</div>`
      : `<div class="list"><div class="empty-state">Nothing scanned yet. Set a bin and scan your first bag.</div></div>`;
    $("#homeBody").innerHTML = out;
    $("#homeBody").querySelectorAll("[data-place]").forEach(b => b.onclick = () => { const d = b.closest("[data-s]"); placeSheet(+d.dataset.s, d.dataset.n, d.dataset.note); });
  } catch (e) { $("#homeBody").innerHTML = `<div class="card">Could not load: ${esc(e.message)}</div>`; }
}
function placeSheet(id, name, note) {
  openSheet(`<h3>Where is <span class="mono">${esc(name)}</span> now?</h3>
   <label>Bin path<input class="field mono" name="path" placeholder="Cabinet A / Drawer 3 / Bin 2" autocomplete="off"></label>
   <label>Note, if there is no bin<textarea class="field" name="note" placeholder="Blue box under the desk">${esc(note || "")}</textarea></label>
   <button class="btn primary" type="submit">Save</button>`,
    async f => {
      const path = (f.get("path") || "").trim(), n = (f.get("note") || "").trim();
      try { await api(`/api/stock/${id}/place`, { path: path || null, note: path && n === (note || "") ? null : n }); toast("Saved"); state.view === "find" ? runFind() : loadHome(); }
      catch (e) { toast(e.message); }
    });
}

/* ---------- find ---------- */
let ft;
async function runFind() {
  const q = $("#q").value.trim(), box = $("#res");
  if (!q) { try { await loadCats(); renderTree(box); } catch (e) { box.innerHTML = `<div class="card">${esc(e.message)}</div>`; } return; }
  box.innerHTML = `<div class="card"><div class="sk" style="width:50%"></div><div class="sk" style="width:80%;margin-top:10px"></div></div>`;
  try {
    const r = await api("/api/find?q=" + encodeURIComponent(q));
    box.innerHTML = r.length ? r.map(p => `<div class="card" data-peek="${p.id}"><div class="head">${plink(p.id, img(p.thumbnail, p.name), "thumb-link")}<div class="body" style="flex:1;min-width:0"><div class="name">${plink(p.id, esc(p.name), "nm")}</div><div class="desc muted sm">${esc(p.description)}</div>${p.category ? `<div class="catline"><a href="#cat/${p.category_id}">${esc(p.category)}</a></div>` : ""}</div>
      <div class="qty">${esc(p.total)}<small>in stock</small></div></div>
      <div class="where">${p.where.length ? p.where.map(w => `<div class="w"><div>${tag(w.path, w.unplaced)}${qbtn(w.stock_id, p.name, w.qty)}</div>${w.note ? `<div class="note" style="margin:0">${esc(w.note)}</div>` : ""}<div class="rowacts"><button class="btn sm" data-place="${w.stock_id}" data-n="${esc(p.name)}" data-note="${esc(w.note)}">Move or edit note</button><button class="btn sm" data-printstock="${w.stock_id}" data-n="${esc(p.name)}">Print item label</button></div></div>`).join("") : '<div class="muted sm">No stock on hand.</div>'}</div></div>`).join("")
      : `<div class="list"><div class="empty-state">Nothing matches "${esc(q)}". Try fewer words, or part of the part number.<div style="margin-top:12px"><button class="btn sm" type="button" id="addFromFind">Add "${esc(q)}" by hand</button></div></div></div>`;
    const af = $("#addFromFind"); if (af) af.onclick = () => handSheet(q);
    box.querySelectorAll("[data-place]").forEach(b => b.onclick = () => placeSheet(+b.dataset.place, b.dataset.n, b.dataset.note));
    box.querySelectorAll("[data-printstock]").forEach(b => b.onclick = () => printSheet("stockitem", [+b.dataset.printstock], b.dataset.n));
  } catch (e) { box.innerHTML = `<div class="card">${esc(e.message)}</div>`; }
}
$("#q").oninput = () => { clearTimeout(ft); ft = setTimeout(runFind, 250); };
$("#homeQ").onkeydown = e => { if (e.key === "Enter" && e.target.value.trim()) { $("#q").value = e.target.value.trim(); location.hash = "#find"; } };
$("#homeHand").onclick = () => handSheet();
$("#pinBtn").onclick = async () => { const p = await askPin(); if (p) { setPin(p); toast("PIN saved"); } };

/* ---------- categories and browse ---------- */
async function loadCats() { state.cats = await api("/api/categories"); return state.cats; }
const catKids = id => state.cats.filter(c => (c.parent || null) === id && c.count > 0).sort((a, b) => a.name.localeCompare(b.name));
function crumbs(c) {
  const parts = c.path.split("/"), out = ['<a href="#find">All categories</a>']; let acc = [];
  parts.forEach((n, i) => {
    acc.push(n); const hit = state.cats.find(x => x.path === acc.join("/"));
    out.push(i === parts.length - 1 || !hit ? `<b>${esc(n)}</b>` : `<a href="#cat/${hit.id}">${esc(n)}</a>`);
  });
  return out.join('<span class="sep">/</span>');
}
function organiseBanner() {
  const u = state.cats.find(c => c.name === "Unsorted" && !c.parent);
  if (!u || !u.count) return "";
  return `<div class="banner"><p><b>${u.count} ${u.count === 1 ? "part is" : "parts are"} not sorted yet.</b><br><span class="muted">File them using DigiKey's categories, so you can browse and filter.</span></p><button class="btn primary sm" type="button" data-organise>Sort them</button></div>`;
}
function wireOrganise(root) { root.querySelectorAll("[data-organise]").forEach(b => b.onclick = organiseAll); }
async function organiseAll() {
  openSheet(`<h3>Sorting parts</h3><p class="muted sm" id="orgMsg">Looking each one up at DigiKey...</p>`, null, null, "Close");
  let moved = 0, skipped = 0;
  try {
    for (let i = 0; i < 12; i++) {
      const r = await api("/api/organise", { limit: 8 }); moved += r.moved; skipped += r.skipped;
      const m = $("#orgMsg"); if (m) m.textContent = `Filed ${moved}, no match for ${skipped}${r.remaining ? ", " + r.remaining + " to go..." : ""}`;
      if (!r.remaining) break;
    }
    const m = $("#orgMsg"); if (m) m.textContent = `Done. Filed ${moved} ${moved === 1 ? "part" : "parts"}.` + (skipped ? ` ${skipped} had no supplier data: open one and use Edit to pick a category.` : "");
  } catch (e) { const m = $("#orgMsg"); if (m) m.textContent = e.message; }
  await loadCats(); renderTrees(); if (state.view === "find") runFind(); else if (state.view === "cat") loadCat(state.catId);
}
const CHEVRON = '<svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg>';
function treeKids() {
  const m = new Map();
  state.cats.filter(c => c.count > 0).forEach(c => { const k = c.parent || 0; if (!m.has(k)) m.set(k, []); m.get(k).push(c); });
  for (const a of m.values()) a.sort((x, y) => (x.name === "Unsorted") - (y.name === "Unsorted") || x.name.localeCompare(y.name));
  return m;
}
function ancestorsOf(id) {
  const out = []; let c = state.cats.find(x => x.id === id);
  while (c && c.parent) { out.push(c.parent); c = state.cats.find(x => x.id === c.parent); }
  return out;
}
function treeHtml(activeId) {
  const kids = treeKids(), open = new Set([...state.open, ...(activeId ? ancestorsOf(activeId) : [])]);
  const row = (c, d) => {
    const sub = kids.get(c.id) || [], isOpen = sub.length && open.has(c.id);
    return `<div class="tn" style="--d:${d}"><button class="tg ${sub.length ? "" : "ghost"} ${isOpen ? "open" : ""}" type="button" data-tg="${c.id}" aria-label="${isOpen ? "Collapse" : "Expand"} ${esc(c.name)}" ${sub.length ? "" : "disabled tabindex=-1"}>${CHEVRON}</button><a class="tl ${c.id === activeId ? "on" : ""}" href="#cat/${c.id}" data-peekcat="${c.id}">${esc(c.name)}</a><span class="tc">${esc(c.count)}</span></div>`
      + (isOpen ? sub.map(k => row(k, d + 1)).join("") : "");
  };
  return (kids.get(0) || []).map(c => row(c, 0)).join("");
}
function renderTrees() {
  const active = state.view === "cat" ? state.catId : null;
  $("#treeSide").innerHTML = `<div class="side-h">Categories</div>${treeHtml(active)}`;
  const box = $("#treeBox"); if (box) box.innerHTML = treeHtml(null);
}
document.addEventListener("click", e => {
  const g = e.target.closest("[data-tg]"); if (!g) return;
  const id = +g.dataset.tg; state.open.has(id) ? state.open.delete(id) : state.open.add(id);
  localStorage.treeOpen = JSON.stringify([...state.open]); renderTrees();
});
function renderTree(box) {
  const kids = treeKids(), roots = kids.get(0) || [];
  box.innerHTML = organiseBanner() + `<h2>Browse by category <small>${roots.length}</small></h2>` + (roots.length
    ? `<div class="list tree landing-tree" id="treeBox">${treeHtml(null)}</div>
       <div class="landing-grid">${roots.map(c => `<a class="catcard" href="#cat/${c.id}" data-peekcat="${c.id}"><span class="n">${esc(c.count)}</span><b>${esc(c.name)}</b><small>${esc((kids.get(c.id) || []).slice(0, 3).map(k => k.name).join(", "))}${(kids.get(c.id) || []).length > 3 ? ", ..." : ""}</small></a>`).join("")}</div>`
    : `<div class="list"><div class="empty-state">Nothing to browse yet. Scan a bag and its category appears here.</div></div>`);
  wireOrganise(box);
}

/* ---------- previews: hover on a computer, tap the picture on a phone ---------- */
const HOVER = matchMedia("(hover: hover) and (pointer: fine)").matches;
const peekCache = new Map();
async function peekData(kind, id) {
  const k = kind + id; if (!peekCache.has(k)) peekCache.set(k, api(`/api/peek/${kind}/${id}`));
  try { return await peekCache.get(k); } catch (e) { peekCache.delete(k); throw e; }
}
function peekPartHtml(d) {
  return `<div class="peek">${d.image ? `<img class="peek-img" src="${esc(d.image)}" alt="">` : ""}
    <div><div class="name">${esc(d.name)}</div><div class="muted sm">${esc(d.description || "")}</div>${d.category ? `<div class="catline">${esc(d.category)}</div>` : ""}</div>
    ${d.specs.length ? `<div class="list" style="box-shadow:none"><table class="kv">${d.specs.map(s => `<tr><td>${esc(s.name)}</td><td>${esc(s.value)}</td></tr>`).join("")}</table></div>${d.more_specs ? `<div class="sm muted">and ${d.more_specs} more</div>` : ""}` : ""}
    <h4>${d.where.length ? `${esc(d.total)} in stock` : "Not in stock"}</h4>
    ${d.where.length ? `<div class="where">${d.where.map(w => `<div class="w2">${tag(w.path, w.unplaced)}<span class="mono">${esc(w.qty)}</span>${w.note ? `<div class="note" style="margin:0;width:100%">${esc(w.note)}</div>` : ""}</div>`).join("")}</div>` : ""}</div>`;
}
function peekCatHtml(d) {
  return `<div class="peek"><div><div class="name" style="font-family:var(--sans)">${esc(d.name)}</div><div class="muted sm">${esc(d.count)} ${d.count === 1 ? "part" : "parts"}</div></div>
    ${d.children.length ? `<div><h4>Sub-categories</h4><div class="chips" style="margin:6px 0 0">${d.children.map(k => `<a class="chip" href="#cat/${k.id}">${esc(k.name)} <small>${esc(k.count)}</small></a>`).join("")}</div></div>` : ""}
    ${d.parts.length ? `<div><h4>Parts</h4><div class="pgrid">${d.parts.map(p => `<a href="#part/${p.id}" title="${esc(p.name)}">${img(p.thumbnail, p.name)}<span>${esc(p.name)}</span></a>`).join("")}</div></div>` : ""}</div>`;
}
const pop = $("#pop"); let showT, hideT;
addEventListener("mousemove", e => { state.mx = e.clientX; state.my = e.clientY; }, { passive: true });
function placePop(rect, flyout) {
  const w = pop.offsetWidth, h = pop.offsetHeight, vw = innerWidth, vh = innerHeight;
  let x, y;
  if (flyout) {  // a category in the sidebar: open beside the sidebar, level with the row
    x = Math.max(rect.right, $("#treeSide").getBoundingClientRect().right) + 8; y = rect.top - 8;
  } else {       // a part row is wide, so follow the pointer like a tooltip
    x = (state.mx ?? rect.left) + 24; y = (state.my ?? rect.top) - 24;
    if (x + w > vw - 8) x = Math.max(8, (state.mx ?? rect.right) - w - 24);
  }
  pop.style.left = x + "px"; pop.style.top = Math.max(68, Math.min(y, vh - h - 90)) + "px";
}
async function showPop(el) {
  const part = el.dataset.peek, cat = el.dataset.peekcat;
  try {
    const d = part ? await peekData("part", part) : await peekData("category", cat);
    if (state.hoverEl !== el) return;
    pop.innerHTML = part ? peekPartHtml(d) : peekCatHtml(d); pop.hidden = false;
    placePop(el.getBoundingClientRect(), !part && !!el.closest("#treeSide"));
  } catch { /* a preview is a nicety */ }
}
function hidePop() { clearTimeout(showT); clearTimeout(hideT); hideT = setTimeout(() => { pop.hidden = true; state.hoverEl = null; }, 150); }
document.addEventListener("mouseover", e => {
  if (!HOVER) return;
  const el = e.target.closest("[data-peek],[data-peekcat]");
  if (e.target.closest("#pop")) { clearTimeout(hideT); return; }
  if (!el) return hidePop();
  if (el !== state.hoverEl) { clearTimeout(hideT); clearTimeout(showT); state.hoverEl = el; showT = setTimeout(() => showPop(el), 200); }
  else clearTimeout(hideT);
});
document.addEventListener("mouseout", e => { if (HOVER && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest("[data-peek],[data-peekcat],#pop"))) hidePop(); });
addEventListener("hashchange", () => { pop.hidden = true; state.hoverEl = null; });
addEventListener("scroll", () => { if (!pop.hidden) { pop.hidden = true; state.hoverEl = null; } }, { passive: true });
async function peekSheet(id) {
  try {
    const d = await peekData("part", id);
    openSheet(peekPartHtml(d) + `<a class="btn primary" href="#part/${id}" id="peekOpen">Open item</a>`, null, null, "Close");
    $("#peekOpen").onclick = () => $("#sheet").close();
  } catch (e) { toast(e.message); }
}
// touch screens have no hover: tapping a part's picture opens the same preview
document.addEventListener("click", e => {
  if (HOVER) return;
  const th = e.target.closest(".thumb"), row = th && th.closest("[data-peek]");
  if (row) { e.preventDefault(); e.stopPropagation(); peekSheet(+row.dataset.peek); }
}, true);

const SORTS = [["relevance", "Best match"], ["newest", "Newest"], ["name", "Name"], ["stock", "Most stock"]];
async function loadCat(id) {
  if (!state.cats.length) await loadCats();
  const c = state.cats.find(x => x.id === id), top = $("#catTop");
  if (!c) { top.innerHTML = '<div class="card">That category no longer exists.</div>'; $("#catRes").innerHTML = ""; return; }
  const kids = catKids(id);
  top.innerHTML = `<div class="crumbs" style="margin-top:6px">${crumbs(c)}</div><h1 style="font-size:28px;margin:0">${esc(c.name)}</h1>
    ${kids.length ? `<div class="chips">${kids.map(k => `<a class="chip" href="#cat/${k.id}">${esc(k.name)} <small>${k.count}</small></a>`).join("")}</div>` : ""}
    <div class="controls"><input id="catQ" class="field" type="search" placeholder="Search in ${esc(c.name)}" value="${esc(state.cat.q)}" autocomplete="off">
    <select id="catSort" class="field" aria-label="Sort by">${SORTS.map(([v, l]) => `<option value="${v}" ${state.cat.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>`;
  let dt; $("#catQ").oninput = e => { clearTimeout(dt); dt = setTimeout(() => { state.cat.q = e.target.value.trim(); loadCatResults(); }, 250); };
  $("#catSort").onchange = e => { state.cat.sort = e.target.value; loadCatResults(); };
  loadCatResults();
}
async function loadCatResults() {
  const box = $("#catRes"), c = state.cat;
  const qs = new URLSearchParams({ category: c.id, q: c.q, sort: c.sort }); Object.entries(c.f).forEach(([n, vs]) => vs.forEach(v => qs.append("f", n + "::" + v)));
  if (!box.firstChild) box.innerHTML = `<div class="list">${'<div class="row"><div class="thumb empty sk"></div><div class="body"><div class="sk" style="width:55%"></div><div class="sk" style="width:80%;margin-top:8px"></div></div></div>'.repeat(3)}</div>`;
  try {
    const r = await api("/api/browse?" + qs);
    const pills = Object.entries(c.f).flatMap(([n, vs]) => vs.map(v => `<button class="pill" data-rm="${esc(n)}::${esc(v)}">${esc(n)}: ${esc(v)} <b>&times;</b></button>`)).join("");
    const cat = state.cats.find(x => x.id === c.id);
    box.innerHTML = (cat && cat.name === "Unsorted" ? organiseBanner() : "")
      + (r.facets.length ? `<div class="facets">${r.facets.map((f, i) => `<button class="chip ${f.values.some(v => v.selected) ? "on" : ""}" data-f="${i}">${esc(f.name)} <small>${f.values.length}</small></button>`).join("")}</div>` : "")
      + (pills ? `<div class="pills">${pills}</div>` : "")
      + `<h2 style="margin-top:6px">${r.total} ${r.total === 1 ? "part" : "parts"}</h2>`
      + (r.parts.length ? `<div class="list">${r.parts.map(p => `<a class="row catrow" href="#part/${p.id}" data-peek="${p.id}">${img(p.thumbnail, p.name)}<div class="body"><div class="name">${esc(p.name)}</div><div class="desc">${esc(p.description || "")}</div>
          ${p.specs.length ? `<div class="specs">${p.specs.map(s => `<span class="sv" title="${esc(s.name)}">${esc(s.value)}</span>`).join("")}</div>` : ""}</div>
          <div class="qty">${esc(p.total)}<small>in stock</small></div></a>`).join("")}</div>`
        : `<div class="list"><div class="empty-state">No parts match.${Object.keys(c.f).length ? " Remove a filter to see more." : ""}</div></div>`);
    box.querySelectorAll("[data-f]").forEach(b => b.onclick = () => facetSheet(r.facets[+b.dataset.f]));
    box.querySelectorAll("[data-rm]").forEach(b => b.onclick = () => { const [n, v] = b.dataset.rm.split("::"); state.cat.f[n] = (state.cat.f[n] || []).filter(x => x !== v); if (!state.cat.f[n].length) delete state.cat.f[n]; loadCatResults(); });
    wireOrganise(box);
  } catch (e) { box.innerHTML = `<div class="card">${esc(e.message)}</div>`; }
}
function facetSheet(f) {
  openSheet(`<h3>${esc(f.name)}</h3><div class="checks">${f.values.map(v => `<label class="chk"><input type="checkbox" name="v" value="${esc(v.value)}" ${v.selected ? "checked" : ""}><span>${esc(v.value)}</span><small>${v.count}</small></label>`).join("")}</div>
    <button class="btn primary" type="submit">Show results</button><button class="btn quiet" type="button" id="clrF">Clear this filter</button>`,
    fd => { const vs = fd.getAll("v"); if (vs.length) state.cat.f[f.name] = vs; else delete state.cat.f[f.name]; loadCatResults(); });
  $("#clrF").onclick = () => { delete state.cat.f[f.name]; $("#sheet").close(); loadCatResults(); };
}

/* ---------- item page ---------- */
async function loadPart(id) {
  const box = $("#partBody");
  box.innerHTML = `<button class="back" id="back"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>Back</button><div class="card"><div class="sk" style="width:55%;height:22px"></div><div class="sk" style="width:80%;margin-top:12px"></div></div>`;
  $("#back").onclick = goBack;
  try {
    const d = await api("/api/part/" + id);
    const dk = d.suppliers.map(s => `<tr><td>DigiKey ${esc(s.variant || "")}</td><td class="mono">${safeUrl(s.link) ? `<a href="${esc(s.link)}" target="_blank" rel="noopener noreferrer">${esc(s.sku)}</a>` : esc(s.sku)}</td></tr>`).join("");
    box.innerHTML = `<button class="back" id="back"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>Back</button>
     <div class="hero">${d.image ? `<img src="${esc(d.image)}" alt="">` : ""}<div><h1>${esc(d.name)}</h1><p class="muted" style="margin-top:6px">${esc(d.description || "No description yet.")}</p></div></div>
     <div class="facts"><div><small>In stock</small><b>${esc(d.total)}</b></div><div><small>Last scanned</small><b>${esc(d.last_scanned || "never")}</b></div><div><small>Category</small><b>${d.category_id ? `<a href="#cat/${d.category_id}" style="color:inherit">${esc(d.category.split("/").pop())}</a>` : "none"}</b></div></div>
     <div class="actions2"><button class="btn primary" id="printPart">Print part label</button><button class="btn" id="photoPart">${d.image ? "Change photo" : "Add photo"}</button></div>
     <input id="photoFile" type="file" accept="image/*" capture="environment" hidden>
     <div class="linkrow"><button class="btn quiet sm" id="editPart">Edit name and description</button>${safeUrl(d.link) ? `<a class="btn quiet sm" href="${esc(d.link)}" target="_blank" rel="noopener noreferrer">Datasheet</a>` : ""}<a class="btn quiet sm" href="${esc(d.inventree_url)}" target="_blank" rel="noopener noreferrer">Open in InvenTree</a></div>
     <h2>Where it is <small>${d.stock.length} ${d.stock.length === 1 ? "line" : "lines"}</small></h2>
     <div class="list">${d.stock.length ? d.stock.map(s => `<div class="line"><div class="top2">${tag(s.path, s.unplaced)}<span class="sm muted">quantity ${qbtn(s.stock_id, d.name, s.qty)}</span></div>
        ${s.note ? `<div class="note" style="margin:0">${esc(s.note)}</div>` : ""}
        ${s.details ? `<div class="sm muted">${esc(s.details)}</div>` : ""}<div class="sm muted">Added ${esc(s.date)}${s.batch ? ` &nbsp;<span class="mono">${esc(s.batch)}</span>` : ""}</div>
        <div class="rowacts"><button class="btn sm" data-place="${s.stock_id}" data-n="${esc(d.name)}" data-note="${esc(s.note)}">Move or edit note</button><button class="btn sm" data-printstock="${s.stock_id}">Print item label</button></div></div>`).join("") : '<div class="empty-state">No stock on hand.</div>'}</div>
     ${d.manufacturers.length || dk ? `<h2>Part details</h2><div class="list"><table class="kv">${d.manufacturers.map(m => `<tr><td>Manufacturer</td><td>${esc(m.name)}</td></tr><tr><td>Manufacturer part no.</td><td class="mono">${esc(m.mpn)}</td></tr>`).join("")}${dk}</table></div>` : ""}
     ${d.params.length ? `<h2>Specifications <small>${d.params.length}</small></h2><div class="list"><table class="kv">${d.params.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.value)}</td></tr>`).join("")}</table></div>` : ""}`;
    $("#back").onclick = goBack;
    $("#editPart").onclick = async () => {
      try { await loadCats(); } catch { /* the picker is optional */ }
      openSheet(`<h3>Edit item</h3>
      <label>Name<input class="field mono" name="name" value="${esc(d.name)}" required></label>
      <label>Description<textarea class="field" name="description">${esc(d.description || "")}</textarea></label>
      <label>Category<select class="field" name="category">${state.cats.slice().sort((a, b) => a.path.localeCompare(b.path)).map(c => `<option value="${c.id}" ${c.id === d.category_id ? "selected" : ""}>${esc(c.path.split("/").join(" / "))}</option>`).join("")}</select></label>
      <button class="btn primary" type="submit">Save</button>`,
        async f => { try { await api(`/api/part/${id}/edit`, { name: f.get("name"), description: f.get("description"), category: +f.get("category") || null }); toast("Saved"); loadPart(id); } catch (e) { toast(e.message); } });
    };
    box.querySelectorAll("[data-place]").forEach(b => b.onclick = () => placeSheet(+b.dataset.place, b.dataset.n, b.dataset.note));
    $("#printPart").onclick = () => printSheet("part", [id], d.name);
    $("#photoPart").onclick = () => $("#photoFile").click();
    $("#photoFile").onchange = async e => {
      const f = e.target.files[0]; if (!f) return;
      toast("Uploading photo..."); try { await uploadPhoto(id, f); toast("Photo saved"); loadPart(id); } catch (x) { toast(x.message); }
    };
    box.querySelectorAll("[data-printstock]").forEach(b => b.onclick = () => printSheet("stockitem", [+b.dataset.printstock], d.name));
  } catch (e) { box.innerHTML = `<button class="back" id="back">Back</button><div class="card">Could not load this item: ${esc(e.message)}</div>`; $("#back").onclick = goBack; }
}
function goBack() { history.length > 1 ? history.back() : (location.hash = "#find"); }

/* ---------- router ---------- */
function route() {
  const h = location.hash.slice(1); let v = "home", arg = null;
  if (h.startsWith("part/") && +h.slice(5)) { v = "part"; arg = +h.slice(5); }
  else if (h.startsWith("cat/") && +h.slice(4)) { v = "cat"; arg = +h.slice(4); }
  else if (["home", "scan", "find"].includes(h)) v = h;
  const key = v + ":" + (arg ?? ""); if (key === state.key) return;
  state.key = key; state.view = v; state.partId = arg; state.catId = arg;
  if (v === "cat" && state.cat.id !== arg) state.cat = { id: arg, q: "", sort: "relevance", f: {} };
  for (const n of ["home", "scan", "find", "part", "cat"]) {
    const s = $("#v-" + n); s.hidden = n !== v; if (n === v) { s.classList.remove("in"); void s.offsetWidth; s.classList.add("in"); }
  }
  document.querySelectorAll(".tabs a").forEach(a => a.dataset.v === (v === "cat" ? "find" : v) ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  v === "scan" ? startCam() : stopCam();
  document.body.classList.toggle("has-tree", v === "find" || v === "cat");
  if (v === "find" || v === "cat") (state.cats.length ? Promise.resolve() : loadCats()).then(renderTrees).catch(() => {});
  if (v === "home") loadHome();
  if (v === "find") { runFind(); $("#q").focus({ preventScroll: true }); }
  if (v === "part") loadPart(arg);
  if (v === "cat") loadCat(arg);
  window.scrollTo(0, 0);
}
addEventListener("hashchange", route);
if (state.pin) setPin(state.pin);
renderBin(); route();
