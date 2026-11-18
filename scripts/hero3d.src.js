// The 3D chip on the home page. Bundled into public/vendor/hero3d.js by scripts/vendor.sh (three.js is tree-shaken to what is used here).
import {
  ACESFilmicToneMapping, BoxGeometry, CanvasTexture, CircleGeometry, DirectionalLight, Group, Mesh, MeshBasicMaterial, MeshStandardMaterial,
  PerspectiveCamera, PlaneGeometry, PMREMGenerator, Scene, SRGBColorSpace, WebGLRenderer,
} from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

const GOLD = 0xe6b02e, BODY = 0x12161c;

function marking(label) {
  const c = document.createElement("canvas"); c.width = c.height = 512; const x = c.getContext("2d");
  x.fillStyle = "#d8dee8"; x.textAlign = "left"; x.textBaseline = "alphabetic";
  x.font = "600 74px 'IBM Plex Sans', system-ui, sans-serif"; x.fillText("invscan", 70, 232);
  x.font = "500 29px 'IBM Plex Mono', ui-monospace, monospace"; x.globalAlpha = 0.85; x.fillText(label, 72, 292);
  x.font = "400 23px 'IBM Plex Mono', ui-monospace, monospace"; x.globalAlpha = 0.55; x.fillText("2230  W39137.00  CN", 72, 336);
  x.globalAlpha = 0.5; x.beginPath(); x.arc(78, 92, 15, 0, 7); x.fill();  // pin-1 dimple
  const t = new CanvasTexture(c); t.colorSpace = SRGBColorSpace; t.anisotropy = 4; return t;
}

function blob() {
  const c = document.createElement("canvas"); c.width = c.height = 128; const x = c.getContext("2d");
  const g = x.createRadialGradient(64, 64, 4, 64, 64, 62); g.addColorStop(0, "rgba(0,0,0,.55)"); g.addColorStop(1, "rgba(0,0,0,0)");
  x.fillStyle = g; x.fillRect(0, 0, 128, 128); return new CanvasTexture(c);
}

function chip(label) {
  const g = new Group(), SIZE = 2, H = 0.3;
  const body = new Mesh(new RoundedBoxGeometry(SIZE, H, SIZE, 3, 0.05), new MeshStandardMaterial({ color: BODY, roughness: 0.5, metalness: 0.15 }));
  g.add(body);
  const top = new Mesh(new PlaneGeometry(SIZE * 0.96, SIZE * 0.96), new MeshStandardMaterial({ map: marking(label), transparent: true, roughness: 0.6, metalness: 0, depthWrite: false }));
  top.rotation.x = -Math.PI / 2; top.position.y = H / 2 + 0.002; g.add(top);
  const gold = new MeshStandardMaterial({ color: GOLD, roughness: 0.26, metalness: 1 });
  const shoulder = new BoxGeometry(0.2, 0.03, 0.06), foot = new BoxGeometry(0.17, 0.03, 0.06);
  for (let side = 0; side < 4; side++) {
    const lead = new Group();
    for (let i = 0; i < 12; i++) {
      const l = new Group(), a = new Mesh(shoulder, gold), b = new Mesh(foot, gold);
      a.position.set(0.1, -0.04, 0); a.rotation.z = -0.55;  // the bend down from the body
      b.position.set(0.27, -0.13, 0);                        // the flat foot that touches the board
      l.add(a, b); l.position.set(SIZE / 2 - 0.02, 0, (i - 5.5) * 0.14); lead.add(l);
    }
    lead.rotation.y = (side * Math.PI) / 2; g.add(lead);
  }
  return g;
}

export function mountChip(canvas, { label = "MC9S08PA60AVLF" } = {}) {
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.toneMapping = ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = SRGBColorSpace;
  const scene = new Scene(), env = new PMREMGenerator(renderer);
  scene.environment = env.fromScene(new RoomEnvironment(), 0.04).texture;
  const key = new DirectionalLight(0xffe2a0, 1.6); key.position.set(-3, 5, 2.5); scene.add(key);
  const camera = new PerspectiveCamera(28, 1, 0.1, 50); camera.position.set(0, 3.7, 7.4); camera.lookAt(0, -0.1, 0);
  const holder = new Group(), part = chip(label); holder.add(part); scene.add(holder);
  const shadow = new Mesh(new CircleGeometry(1.9, 40), new MeshBasicMaterial({ map: blob(), transparent: true, depthWrite: false }));
  shadow.rotation.x = -Math.PI / 2; shadow.position.y = -0.62; scene.add(shadow);

  const size = () => {  // fit the chip into whatever shape the panel gives us: pull the camera back when the canvas is narrow
    const r = canvas.getBoundingClientRect(); if (!r.width || !r.height) return;
    renderer.setSize(r.width, r.height, false); camera.aspect = r.width / r.height;
    const back = Math.max(1, 1.2 / camera.aspect); camera.position.set(0, 3.7 * back, 7.4 * back); camera.lookAt(0, -0.1, 0); camera.updateProjectionMatrix();
  };
  new ResizeObserver(size).observe(canvas); size();

  let px = 0, py = 0, tx = 0, ty = 0, t0 = performance.now(), raf = 0, visible = true, active = true;
  addEventListener("pointermove", e => { const r = canvas.getBoundingClientRect(); tx = ((e.clientX - r.left) / Math.max(r.width, 1) - 0.5) * 2; ty = ((e.clientY - r.top) / Math.max(r.height, 1) - 0.5) * 2; }, { passive: true });
  const draw = now => {
    const t = (now - t0) / 1000; px += (Math.max(-1.4, Math.min(1.4, tx)) - px) * 0.06; py += (Math.max(-1.4, Math.min(1.4, ty)) - py) * 0.06;
    holder.rotation.y = still ? 0.6 : t * 0.28 + px * 0.55; holder.rotation.x = 0.1 + (still ? 0 : py * 0.2);
    holder.position.y = still ? 0 : Math.sin(t * 1.3) * 0.05;
    shadow.scale.setScalar(1 - (still ? 0 : Math.sin(t * 1.3) * 0.03));
    renderer.render(scene, camera);
  };
  const loop = now => { raf = 0; if (!visible || !active || document.hidden) return; draw(now); raf = requestAnimationFrame(loop); };
  const go = () => { if (still) { draw(performance.now()); return; } if (!raf && visible && active) raf = requestAnimationFrame(loop); };
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; go(); }).observe(canvas);
  document.addEventListener("visibilitychange", go);
  go();
  return { setActive(on) { active = on; if (on) { size(); go(); } } };
}
