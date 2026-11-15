// 3D drawings on the glass, rendered with three.js. Loaded on demand (React.lazy), so the
// library only downloads the first time the agent draws in 3D.
//
// Four scenes cover the patterns the coach explains most:
//   bars  - an array as bars, with pointers and optional water between two of them
//   grid  - a 0/1 grid as land and water tiles
//   tree  - a binary tree from level-order values ("null" for gaps)
//   graph - nodes and edges, laid out by a small force simulation
// Drag to turn the scene. It turns slowly by itself unless the viewer prefers reduced motion.

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

export type SceneKind = "bars" | "grid" | "tree" | "graph";
export interface SceneSpec {
  scene: SceneKind;
  values: string[];
  pointers: Map<number, string[]>;
  water: [number, number] | null;
  highlight: Set<string>;
  edges: [number, number][];
}

const C = {
  bg: 0x0a1319, ground: 0x0c161d, line: 0x223440, surface: 0x48708a,
  seafoam: 0x7fd1c1, baltic: 0x6b9fe0, sky: 0x86bbd8, skyDeep: 0x5f9cc4, text: "#eaf2f7", dim: "#8aa0af",
};

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
const easeOut = (t: number) => 1 - Math.pow(1 - Math.min(Math.max(t, 0), 1), 3);

/** A crisp text label that always faces the camera. */
function label(text: string, color: string, px = 48, weight = 600): THREE.Sprite {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  const font = `${weight} ${px}px "JetBrains Mono", ui-monospace, monospace`;
  ctx.font = font;
  const w = Math.ceil(ctx.measureText(text).width) + px * 0.6;
  canvas.width = w; canvas.height = Math.ceil(px * 1.4);
  ctx.font = font; ctx.fillStyle = color; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(text, w / 2, canvas.height / 2);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  const h = 0.42 * (px / 48);
  sprite.scale.set(h * (w / canvas.height), h, 1);
  return sprite;
}

function solid(color: number, opts: Partial<THREE.MeshPhysicalMaterialParameters> = {}): THREE.MeshPhysicalMaterial {
  return new THREE.MeshPhysicalMaterial({ color, roughness: 0.35, metalness: 0.05, clearcoat: 0.6, clearcoatRoughness: 0.25, ...opts });
}

/** A cylinder from a to b, for tree and graph edges. */
function edge(a: THREE.Vector3, b: THREE.Vector3, color: number): THREE.Mesh {
  const length = a.distanceTo(b);
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, length, 10), solid(color, { roughness: 0.6, clearcoat: 0 }));
  mesh.position.copy(a).add(b).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
  return mesh;
}

type Grower = { object: THREE.Object3D; delay: number; axis: "y" | "all" };
type Built = { group: THREE.Group; growers: Grower[]; tick?: (t: number) => void };

function buildBars(spec: SceneSpec): Built {
  const group = new THREE.Group();
  const growers: Grower[] = [];
  const nums = spec.values.map((v) => Number(v));
  const max = Math.max(1, ...nums.map((n) => (Number.isFinite(n) ? Math.abs(n) : 0)));
  const step = 1.1;
  const x0 = -((nums.length - 1) * step) / 2;
  const height = (n: number) => (Number.isFinite(n) ? Math.max(0.12, (Math.abs(n) / max) * 4) : 0.12);
  nums.forEach((n, i) => {
    const h = height(n);
    const lit = spec.highlight.has(String(i)) || spec.pointers.has(i);
    const geo = new THREE.BoxGeometry(0.8, h, 0.8);
    geo.translate(0, h / 2, 0);
    const bar = new THREE.Mesh(geo, solid(lit ? C.sky : C.surface, lit ? { emissive: C.skyDeep, emissiveIntensity: 0.25 } : {}));
    bar.castShadow = true; bar.receiveShadow = true;
    bar.position.x = x0 + i * step;
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: lit ? 0xd3e8f4 : 0x4a6678, transparent: true, opacity: 0.7 }));
    bar.add(edges);
    group.add(bar);
    growers.push({ object: bar, delay: i * 0.05, axis: "y" });
    const value = label(spec.values[i], C.text, 44);
    value.position.set(bar.position.x, h + 0.38, 0);
    group.add(value);
    const index = label(String(i), C.dim, 34, 500);
    index.position.set(bar.position.x, 0.26, 0.7);
    group.add(index);
    const names = spec.pointers.get(i);
    if (names) {
      const tag = label(names.join(" "), "#86bbd8", 40, 700);
      tag.position.set(bar.position.x, 0.3, 1.8);
      group.add(tag);
      const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.3, 16), solid(C.sky, { emissive: C.sky, emissiveIntensity: 0.4 }));
      arrow.rotation.x = -Math.PI / 2; // lies on the floor, pointing back at the bar it names
      arrow.position.set(bar.position.x, 0.14, 1.12);
      group.add(arrow);
    }
  });

  let tick: Built["tick"];
  if (spec.water) {
    const [a, b] = spec.water[0] <= spec.water[1] ? spec.water : [spec.water[1], spec.water[0]];
    if (a >= 0 && b < nums.length && a < b) {
      const level = Math.min(height(nums[a]), height(nums[b]));
      const xa = x0 + a * step + 0.4, xb = x0 + b * step - 0.4, width = xb - xa;
      const body = new THREE.Mesh(new THREE.BoxGeometry(width, level, 0.78),
        solid(C.skyDeep, { transparent: true, opacity: 0.32, roughness: 0.1, clearcoat: 1, emissive: C.skyDeep, emissiveIntensity: 0.15, depthWrite: false }));
      body.geometry.translate(0, level / 2, 0); // grow from the floor up
      body.position.set((xa + xb) / 2, 0, 0);
      group.add(body);
      growers.push({ object: body, delay: nums.length * 0.05 + 0.15, axis: "y" });
      // A rippling surface on top of the water.
      const surface = new THREE.Mesh(new THREE.PlaneGeometry(width, 0.78, 48, 6), solid(C.sky, { transparent: true, opacity: 0.55, roughness: 0.05, side: THREE.DoubleSide, depthWrite: false }));
      surface.rotation.x = -Math.PI / 2;
      surface.position.set((xa + xb) / 2, level, 0);
      group.add(surface);
      growers.push({ object: surface, delay: nums.length * 0.05 + 0.4, axis: "all" });
      const base = (surface.geometry.attributes.position.array as Float32Array).slice();
      tick = (t) => {
        const pos = surface.geometry.attributes.position;
        for (let i = 0; i < pos.count; i++) {
          const x = base[i * 3], y = base[i * 3 + 1];
          pos.setZ(i, Math.sin(x * 2.2 + t * 2) * 0.03 + Math.cos(y * 5 + t * 1.6) * 0.015);
        }
        pos.needsUpdate = true;
      };
    }
  }
  return { group, growers, tick };
}

function buildGrid(spec: SceneSpec): Built {
  const group = new THREE.Group();
  const growers: Grower[] = [];
  const rows = spec.values.map((r) => r.split(/[\s,]+/).filter(Boolean));
  const cols = Math.max(...rows.map((r) => r.length));
  const s = 1.0;
  rows.forEach((row, r) => row.forEach((cell, c) => {
    const land = cell === "1" || cell.toLowerCase() === "x" || cell === "#";
    const lit = spec.highlight.has(`${r}:${c}`);
    const h = land ? (lit ? 0.9 : 0.6) : 0.08;
    const geo = new THREE.BoxGeometry(0.92, h, 0.92);
    geo.translate(0, h / 2, 0);
    const color = lit ? C.sky : land ? C.seafoam : 0x1b3a4f;
    const mesh = new THREE.Mesh(geo, solid(color, land ? { roughness: 0.55 } : { roughness: 0.08, transparent: true, opacity: 0.85 }));
    mesh.castShadow = land; mesh.receiveShadow = true;
    mesh.position.set((c - (cols - 1) / 2) * s, 0, (r - (rows.length - 1) / 2) * s);
    group.add(mesh);
    growers.push({ object: mesh, delay: (r + c) * 0.04, axis: "y" });
  }));
  return { group, growers };
}

function nodeMesh(text: string, lit: boolean): THREE.Group {
  const g = new THREE.Group();
  const ball = new THREE.Mesh(new THREE.SphereGeometry(0.42, 40, 24), solid(lit ? C.sky : C.baltic, { emissive: lit ? C.skyDeep : 0x1d3a66, emissiveIntensity: 0.35, roughness: 0.25 }));
  ball.castShadow = true;
  g.add(ball);
  // Drawn on top of its own ball, centred whichever way the scene is turned.
  const tag = label(text, lit ? "#0a1319" : "#ffffff", 46, 700);
  tag.material.depthTest = false;
  tag.renderOrder = 10;
  tag.scale.multiplyScalar(0.9);
  g.add(tag);
  return g;
}

function buildTree(spec: SceneSpec): Built {
  const group = new THREE.Group();
  const growers: Grower[] = [];
  const depthOf = (i: number) => Math.floor(Math.log2(i + 1));
  const maxDepth = depthOf(spec.values.length - 1);
  const position = (i: number) => {
    const d = depthOf(i), first = 2 ** d - 1, slot = i - first, slots = 2 ** d;
    const span = 2 ** maxDepth * 1.1;
    return new THREE.Vector3(((slot + 0.5) / slots - 0.5) * span, (maxDepth - d) * 1.5 + 0.6, 0);
  };
  spec.values.forEach((v, i) => {
    if (!v || v.toLowerCase() === "null" || v === "None") return;
    const p = position(i);
    const node = nodeMesh(v, spec.highlight.has(String(i)));
    node.position.copy(p);
    group.add(node);
    growers.push({ object: node, delay: depthOf(i) * 0.18 + i * 0.02, axis: "all" });
    if (i > 0) {
      const parent = Math.floor((i - 1) / 2);
      const pv = spec.values[parent];
      if (pv && pv.toLowerCase() !== "null" && pv !== "None") {
        const e = edge(position(parent), p, C.line);
        group.add(e);
        growers.push({ object: e, delay: depthOf(i) * 0.18, axis: "all" });
      }
    }
  });
  return { group, growers };
}

function buildGraph(spec: SceneSpec): Built {
  const group = new THREE.Group();
  const growers: Grower[] = [];
  const n = spec.values.length;
  // Start on a Fibonacci sphere (deterministic), then relax with a small spring simulation.
  const pts = spec.values.map((_, i) => {
    const y = 1 - (i / Math.max(1, n - 1)) * 2, r = Math.sqrt(1 - y * y), phi = i * 2.399963;
    return new THREE.Vector3(Math.cos(phi) * r, y, Math.sin(phi) * r).multiplyScalar(2.2);
  });
  for (let iter = 0; iter < 240; iter++) {
    const force = pts.map(() => new THREE.Vector3());
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const d = pts[i].clone().sub(pts[j]); const dist = Math.max(d.length(), 0.1);
      const push = d.normalize().multiplyScalar(2.2 / (dist * dist));
      force[i].add(push); force[j].sub(push);
    }
    for (const [a, b] of spec.edges) {
      if (!pts[a] || !pts[b]) continue;
      const d = pts[b].clone().sub(pts[a]); const pull = d.multiplyScalar(0.06 * (d.length() - 1.8));
      force[a].add(pull); force[b].sub(pull);
    }
    pts.forEach((p, i) => p.add(force[i].multiplyScalar(0.12)).multiplyScalar(0.995));
  }
  const center = pts.reduce((acc, p) => acc.add(p), new THREE.Vector3()).multiplyScalar(1 / Math.max(1, n));
  pts.forEach((p) => p.sub(center));
  const lowest = Math.min(...pts.map((p) => p.y));
  pts.forEach((p) => { p.y += 0.7 - lowest; }); // every node sits above the floor
  for (const [a, b] of spec.edges) {
    if (!pts[a] || !pts[b]) continue;
    const e = edge(pts[a], pts[b], C.line);
    group.add(e);
    growers.push({ object: e, delay: 0.3, axis: "all" });
  }
  spec.values.forEach((v, i) => {
    const node = nodeMesh(v, spec.highlight.has(String(i)));
    node.position.copy(pts[i]);
    group.add(node);
    growers.push({ object: node, delay: i * 0.05, axis: "all" });
  });
  return { group, growers };
}

const BUILDERS: Record<SceneKind, (s: SceneSpec) => Built> = { bars: buildBars, grid: buildGrid, tree: buildTree, graph: buildGraph };

export default function Scene3D({ spec, caption }: { spec: SceneSpec; caption: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      setFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(C.bg, 14, 34);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);

    scene.add(new THREE.HemisphereLight(0xb4d9ee, C.bg, 1.25));
    const key = new THREE.DirectionalLight(0xffffff, 1.7);
    key.position.set(6, 12, 8);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -12; key.shadow.camera.right = 12; key.shadow.camera.top = 12; key.shadow.camera.bottom = -12;
    key.shadow.radius = 4;
    scene.add(key);
    const rim = new THREE.PointLight(C.sky, 30, 30);
    rim.position.set(-6, 5, -6);
    scene.add(rim);

    const ground = new THREE.Mesh(new THREE.CircleGeometry(16, 64), new THREE.MeshStandardMaterial({ color: C.ground, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2; ground.position.y = -0.001; ground.receiveShadow = true;
    scene.add(ground);
    const grid = new THREE.GridHelper(24, 24, C.line, C.line);
    (grid.material as THREE.Material).transparent = true; (grid.material as THREE.Material).opacity = 0.35;
    scene.add(grid);

    const built = BUILDERS[spec.scene](spec);
    const pivot = new THREE.Group();
    pivot.add(built.group);
    scene.add(pivot);

    // Frame the content: fit its bounding sphere in view, looking slightly down.
    const box = new THREE.Box3().setFromObject(built.group);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const target = new THREE.Vector3(0, sphere.center.y, 0);
    const fit = spec.scene === "bars" || spec.scene === "grid" ? 0.95 : 1.15;
    const distance = (sphere.radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))) * fit;
    const view = new THREE.Vector3(0, 0.42, 1).normalize().multiplyScalar(distance);

    const still = reducedMotion();
    const scales = built.growers.map((g) => g.object.scale.clone());
    if (!still) built.growers.forEach((g) => (g.axis === "y" ? g.object.scale.setY(0.0001) : g.object.scale.setScalar(0.0001)));

    let yaw = spec.scene === "bars" ? -0.35 : 0.5, pitch = 0, dragging = false, lastX = 0, lastY = 0, idleSince = performance.now();
    const onDown = (e: PointerEvent) => { dragging = true; lastX = e.clientX; lastY = e.clientY; renderer.domElement.setPointerCapture(e.pointerId); };
    const onMove = (e: PointerEvent) => {
      if (!dragging) return;
      yaw += (e.clientX - lastX) * 0.008; pitch = Math.max(-0.35, Math.min(0.6, pitch + (e.clientY - lastY) * 0.005));
      lastX = e.clientX; lastY = e.clientY; idleSince = performance.now();
    };
    const onUp = () => { dragging = false; idleSince = performance.now(); };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerup", onUp);
    renderer.domElement.style.touchAction = "none";
    renderer.domElement.style.cursor = "grab";

    const resize = () => {
      const w = el.clientWidth || 400, h = el.clientHeight || 260;
      renderer.setSize(w, h, false);
      renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%";
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    let visible = true;
    const io = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; });
    io.observe(el);

    const clock = new THREE.Clock();
    let frame = 0;
    const loop = () => {
      frame = requestAnimationFrame(loop);
      if (!visible) return;
      const t = clock.getElapsedTime();
      if (!still) {
        built.growers.forEach((g, i) => {
          const k = easeOut((t - g.delay) / 0.7);
          const s = scales[i];
          if (g.axis === "y") g.object.scale.set(s.x, Math.max(0.0001, s.y * k), s.z);
          else g.object.scale.setScalar(Math.max(0.0001, s.x * k));
        });
        if (!dragging && performance.now() - idleSince > 2500) yaw += 0.0025;
        built.tick?.(t);
      }
      pivot.rotation.y = yaw;
      camera.position.copy(view).applyAxisAngle(new THREE.Vector3(1, 0, 0), -pitch).add(target);
      camera.lookAt(target);
      renderer.render(scene, camera);
    };
    loop();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect(); io.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("pointerup", onUp);
      scene.traverse((o) => {
        const mesh = o as THREE.Mesh;
        mesh.geometry?.dispose();
        const mats = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
        mats.forEach((m) => { (m as THREE.SpriteMaterial).map?.dispose(); m.dispose(); });
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [spec]);

  if (failed) return <div className="muted" style={{ fontSize: 13 }}>This browser cannot show 3D. {caption}</div>;
  return (
    <figure style={{ margin: 0 }}>
      <div ref={host} className="glass-3d" role="img" aria-label={caption || `A 3D ${spec.scene} drawn by Senior`} />
      {caption && <figcaption className="muted" style={{ fontSize: 13, marginTop: 8 }}>{caption}</figcaption>}
      <span className="dim" style={{ fontSize: 11 }}>Drag to turn</span>
    </figure>
  );
}
