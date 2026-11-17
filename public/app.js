ZXingWASM.setZXingModuleOverrides({ locateFile: p => "/static/vendor/" + p });
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { pin: localStorage.pin || "", bin: JSON.parse(localStorage.bin || "null"), view: "", cam: null, paused: false, last: "", lastT: 0, lastSeen: 0, busy: false, firstHome: true };

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
const tag = (path, unplaced) => `<span class="tag${unplaced ? " warn" : ""}" title="${esc(path)}">${esc(path)}</span>`;
const safeUrl = u => /^https?:\/\//i.test(u || "") ? u : "";
const plink = (id, html, cls = "") => `<a class="${cls}" href="#part/${id}">${html}</a>`;
const CHECK = '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>', WARN = '<svg viewBox="0 0 24 24"><path d="M12 7v6M12 17h.01"/></svg>', CROSS = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';
function toast(t) { const d = document.createElement("div"); d.className = "toast"; d.textContent = t; document.body.append(d); setTimeout(() => d.remove(), 2400); }

/* ---------- sheet ---------- */
function openSheet(html, onSubmit, onCancel) {
  const d = $("#sheet"), f = $("#sheetForm");
  f.innerHTML = html + `<button class="btn quiet" type="button" data-x>Cancel</button>`;
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
function refresh() { state.view === "find" ? runFind() : state.view === "home" ? loadHome() : state.view === "part" ? loadPart(state.partId) : 0; }
document.addEventListener("click", e => {
  const b = e.target.closest("[data-qty]"); if (!b) return;
  qtySheet(+b.dataset.id, b.dataset.name, b.dataset.val, b.dataset.after ? r => { b.textContent = r.qty; b.dataset.val = r.qty; } : null);
});

/* ---------- bin ---------- */
function renderBin() {
  const b = $("#binbar");
  if (state.bin) { b.className = "binbar on"; b.innerHTML = `<div class="t"><small>Putting bags in</small>${tag(state.bin.path)}</div><button class="btn sm" data-bin>Change</button>`; }
  else { b.className = "binbar note"; b.innerHTML = `<div class="t"><b>No bin set</b><small>Scan a bin label, or write a note about where each bag goes.</small></div><button class="btn sm" data-bin>Set bin</button>`; }
  b.querySelector("[data-bin]").onclick = binSheet;
}
function setBin(b) { state.bin = b; localStorage.bin = JSON.stringify(b); renderBin(); }
function binSheet() {
  openSheet(`<h3>Where are bags going?</h3>
   <p class="muted sm">Point the camera at a bin label, or type a path. New paths are created.</p>
   <input class="field mono" name="path" placeholder="Cabinet A / Drawer 3 / Bin 2" autocomplete="off">
   <button class="btn primary" type="submit">Use this bin</button>
   <button class="btn" type="button" id="nobin">No bin label: I'll write a note instead</button>`,
    async f => { const p = (f.get("path") || "").trim(); if (p) { try { setBin(await api("/api/bin", { path: p })); } catch (e) { toast(e.message); } } });
  $("#nobin").onclick = () => { setBin(null); $("#sheet").close(); };
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
     ${r.stock_id ? `<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">${tag(r.path || "No location", r.path === "Unplaced")} <span class="sm muted">quantity</span> ${qbtn(r.stock_id, r.name || r.mpn, r.qty).replace("data-qty", 'data-qty data-after="1"')}</div>` : ""}
     ${r.note ? `<div class="note">${esc(r.note)}</div>` : ""}${extra ? `<div class="sm">${extra}</div>` : ""}
     ${r.part_id ? `<div class="acts">${plink(r.part_id, "Open item", "btn sm")}</div>` : ""}</div></div>`;
  $("#resX").onclick = () => { box.hidden = true; };
  const f = $("#finder"); f.classList.remove("f-ok", "f-dup", "f-err"); f.classList.add("f-" + kind); setTimeout(() => f.classList.remove("f-" + kind), 1200);
  window.scrollTo({ top: 0, behavior: "smooth" });
}
async function sendBag(raw, note) {
  state.busy = true;
  try {
    const r = await api("/api/scan", { raw, location_id: state.bin?.id ?? null, qty: +$("#qty").value || null, note: note || null });
    if (r.kind === "bin") { setBin(r); card("", `<div>Bin set</div>${tag(r.path)}`); toast("Bin set"); }
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
function handleCode(text) {
  const now = Date.now();
  if (state.busy || state.paused) return;
  state.last = text; state.lastT = now;
  $("#finder").classList.add("hit"); setTimeout(() => $("#finder").classList.remove("hit"), 400);
  if (text.startsWith("INVSCAN:LOC:") || state.bin) return sendBag(text);
  // bag without a bin: ask where it is going so it can be found later
  const mpn = (text.match(/1P([^\x1d␝]+)/) || [])[1] || "this bag";
  openSheet(`<h3>Where is it going?</h3>
    <p class="muted sm"><span class="mono">${esc(mpn)}</span> has no bin. Write where you put it and you can search for these words later.</p>
    <textarea class="field" name="note" placeholder="Blue box under the desk, left side" required autofocus></textarea>
    <button class="btn primary" type="submit">Save with note</button>
    <button class="btn" type="button" id="setbin">Set a bin instead</button>`,
    f => sendBag(text, f.get("note").trim()));
  $("#setbin").onclick = () => { $("#sheet").close(); setTimeout(binSheet, 60); };
}
async function readImage(src, w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; const x = c.getContext("2d", { willReadFrequently: true });
  draw(x); const rs = await ZXingWASM.readBarcodes(x.getImageData(0, 0, w, h), { formats: ["DataMatrix", "QRCode"], tryHarder: true, maxNumberOfSymbols: 1 });
  return rs[0]?.text;
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
        if (t) {
          // same code still in view: wait until it has been out of frame ~2.5s before reacting again
          const seen = Date.now(), same = t === state.last && seen - state.lastSeen < 2500;
          state.lastSeen = seen;
          if (!same) handleCode(t);
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
    if (t) handleCode(t); else showResult("err", "No code found in the photo", { mpn: "" }, `${bm.width}x${bm.height}. Move closer, keep the label flat, and avoid glare.`);
  } catch (x) { card("err", `<div class="sm">${esc(x.message)}</div>`); }
  e.target.value = "";
};

/* ---------- home ---------- */
function stockRow(s, extra = "") {
  return `<div class="row">${plink(s.part_id, img(s.thumbnail, s.name), "thumb-link")}<div class="body"><div class="name">${plink(s.part_id, esc(s.name), "nm")}</div>
    ${s.description ? `<div class="desc">${esc(s.description)}</div>` : ""}
    <div class="meta">${tag(s.path, s.unplaced)}</div>${s.note ? `<div class="note">${esc(s.note)}</div>` : ""}</div>
    <div class="qty">${qbtn(s.stock_id, s.name, s.qty)}${extra}</div></div>`;
}
async function loadHome() {
  $("#homeBody").innerHTML = `<h2>Loading</h2><div class="list">${'<div class="row"><div class="thumb empty sk"></div><div class="body"><div class="sk" style="width:60%"></div><div class="sk" style="width:85%;margin-top:8px"></div></div></div>'.repeat(3)}</div>`;
  try {
    const h = await api("/api/home");
    $("#stats").innerHTML = `<div><b>${h.counts.parts}</b><span>parts</span></div><div><b>${h.counts.stock}</b><span>stock lines</span></div><div><b>${h.counts.bins}</b><span>bins</span></div>` + (h.unsorted ? `<div><b>${h.unsorted}</b><span>to categorise</span></div>` : "");
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
  if (!q) { box.innerHTML = `<div class="list"><div class="empty-state">Type a part number, a value like "16 bit", or words from a note you wrote.</div></div>`; return; }
  box.innerHTML = `<div class="card"><div class="sk" style="width:50%"></div><div class="sk" style="width:80%;margin-top:10px"></div></div>`;
  try {
    const r = await api("/api/find?q=" + encodeURIComponent(q));
    box.innerHTML = r.length ? r.map(p => `<div class="card"><div class="head">${plink(p.id, img(p.thumbnail, p.name), "thumb-link")}<div class="body" style="flex:1;min-width:0"><div class="name">${plink(p.id, esc(p.name), "nm")}</div><div class="desc muted sm">${esc(p.description)}</div></div>
      <div class="qty">${esc(p.total)}<small>in stock</small></div></div>
      <div class="where">${p.where.length ? p.where.map(w => `<div class="w"><div>${tag(w.path, w.unplaced)}${qbtn(w.stock_id, p.name, w.qty)}</div>${w.note ? `<div class="note" style="margin:0">${esc(w.note)}</div>` : ""}<div><button class="btn sm" data-place="${w.stock_id}" data-n="${esc(p.name)}" data-note="${esc(w.note)}">Move or edit note</button></div></div>`).join("") : '<div class="muted sm">No stock on hand.</div>'}</div></div>`).join("")
      : `<div class="list"><div class="empty-state">Nothing matches "${esc(q)}". Try fewer words, or part of the part number.</div></div>`;
    box.querySelectorAll("[data-place]").forEach(b => b.onclick = () => placeSheet(+b.dataset.place, b.dataset.n, b.dataset.note));
  } catch (e) { box.innerHTML = `<div class="card">${esc(e.message)}</div>`; }
}
$("#q").oninput = () => { clearTimeout(ft); ft = setTimeout(runFind, 250); };
$("#homeQ").onkeydown = e => { if (e.key === "Enter" && e.target.value.trim()) { $("#q").value = e.target.value.trim(); location.hash = "#find"; } };
$("#pinBtn").onclick = async () => { const p = await askPin(); if (p) { setPin(p); toast("PIN saved"); } };

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
     <div class="facts"><div><small>In stock</small><b>${esc(d.total)}</b></div><div><small>Last scanned</small><b>${esc(d.last_scanned || "never")}</b></div><div><small>Category</small><b>${esc(d.category || "none")}</b></div></div>
     <div class="extlinks"><button class="btn sm" id="editPart">Edit name and description</button>${safeUrl(d.link) ? `<a class="btn sm" href="${esc(d.link)}" target="_blank" rel="noopener noreferrer">Datasheet</a>` : ""}<a class="btn sm" href="${esc(d.inventree_url)}" target="_blank" rel="noopener noreferrer">Open in InvenTree</a></div>
     <h2>Where it is <small>${d.stock.length} ${d.stock.length === 1 ? "line" : "lines"}</small></h2>
     <div class="list">${d.stock.length ? d.stock.map(s => `<div class="line"><div class="top2">${tag(s.path, s.unplaced)}<span class="sm muted">quantity ${qbtn(s.stock_id, d.name, s.qty)}</span></div>
        ${s.note ? `<div class="note" style="margin:0">${esc(s.note)}</div>` : ""}
        ${s.details ? `<div class="sm muted">${esc(s.details)}</div>` : ""}<div class="sm muted">Added ${esc(s.date)}${s.batch ? ` &nbsp;<span class="mono">${esc(s.batch)}</span>` : ""}</div>
        <div><button class="btn sm" data-place="${s.stock_id}" data-n="${esc(d.name)}" data-note="${esc(s.note)}">Move or edit note</button></div></div>`).join("") : '<div class="empty-state">No stock on hand.</div>'}</div>
     ${d.manufacturers.length || dk ? `<h2>Part details</h2><div class="list"><table class="kv">${d.manufacturers.map(m => `<tr><td>Manufacturer</td><td>${esc(m.name)}</td></tr><tr><td>Manufacturer part no.</td><td class="mono">${esc(m.mpn)}</td></tr>`).join("")}${dk}</table></div>` : ""}
     ${d.params.length ? `<h2>Specifications <small>${d.params.length}</small></h2><div class="list"><table class="kv">${d.params.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.value)}</td></tr>`).join("")}</table></div>` : ""}`;
    $("#back").onclick = goBack;
    $("#editPart").onclick = () => openSheet(`<h3>Edit item</h3>
      <label>Name<input class="field mono" name="name" value="${esc(d.name)}" required></label>
      <label>Description<textarea class="field" name="description">${esc(d.description || "")}</textarea></label>
      <button class="btn primary" type="submit">Save</button>`,
      async f => { try { await api(`/api/part/${id}/edit`, { name: f.get("name"), description: f.get("description") }); toast("Saved"); loadPart(id); } catch (e) { toast(e.message); } });
    box.querySelectorAll("[data-place]").forEach(b => b.onclick = () => placeSheet(+b.dataset.place, b.dataset.n, b.dataset.note));
  } catch (e) { box.innerHTML = `<button class="back" id="back">Back</button><div class="card">Could not load this item: ${esc(e.message)}</div>`; $("#back").onclick = goBack; }
}
function goBack() { history.length > 1 ? history.back() : (location.hash = "#find"); }

/* ---------- router ---------- */
function route() {
  const h = location.hash.slice(1); let v = "home", arg = null;
  if (h.startsWith("part/") && +h.slice(5)) { v = "part"; arg = +h.slice(5); }
  else if (["home", "scan", "find"].includes(h)) v = h;
  const key = v + ":" + (arg ?? ""); if (key === state.key) return;
  state.key = key; state.view = v; state.partId = arg;
  for (const n of ["home", "scan", "find", "part"]) {
    const s = $("#v-" + n); s.hidden = n !== v; if (n === v) { s.classList.remove("in"); void s.offsetWidth; s.classList.add("in"); }
  }
  document.querySelectorAll(".tabs a").forEach(a => a.dataset.v === v ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  v === "scan" ? startCam() : stopCam();
  if (v === "home") loadHome();
  if (v === "find") { runFind(); $("#q").focus({ preventScroll: true }); }
  if (v === "part") loadPart(arg);
  window.scrollTo(0, 0);
}
addEventListener("hashchange", route);
renderBin(); route();
