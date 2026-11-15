// 로버 콘솔의 3D 지형 보기 (S3c §6.1 Terrain3D, R-06). 로버 콘솔에만 있다 — 현장 화면은 2D만 쓴다.
//
// 화면은 계산하지 않는다. 로버 프로그램이 내주는 세 가지를 받아 그대로 세우고 입힌다(rover/console_map.py):
//   /console/height.json           지형의 높이 격자 → 지형을 세운다
//   /console/science.png?kind=…    과학 가치 지도를 색 입힌 그림 → 지형 위에 입힌다. 색은 프로그램이 정했다
//   /console/science_legend.json   그 그림의 색 눈금·등급 경계·설명 글 → 범례를 그대로 그린다
//   /bundle/tiles/{레이어}/…        2D 지도와 같은 레이어 그림(음영 기복, 경사, 지질 단위, 광물, 바탕 지도, 링크 안 되는 곳, 그림자)
//                                  → 왼쪽 LAYERS에서 켠 것을 2D와 같은 순서로 지형 위에 입힌다. 색은 타일에 칠해져 있는 그대로다
// 그림이 바뀌었는지는 스냅샷의 science_rev로 안다(번호가 바뀔 때만 다시 받는다).
//
// 그 위에 얹는 것(2D 지도와 같은 자료, 같은 색): 우주인, 로버, 계획의 정지점, 다음에 갈 곳까지의 길, 후보 표에서 고른 경로, 관측.
// 선과 표식을 지형에 올려놓을 때의 높이는 받은 높이 격자에서 읽는다 — 그릴 자리를 맞추는 것일 뿐, 경로나 값을 새로 만들지 않는다.
//
// 높이 과장: 이 구역은 가로세로 5 km에 높낮이 차가 200 m쯤이라 실제 비율로는 거의 평평하다. 그래서 높이를 몇 배 키워 보이고,
// 지금 몇 배인지 늘 적어 둔다. 사람이 바꿀 수 있다. 과장은 보기만 바꾼다 — 카드의 경사·시간 같은 값과는 상관없다.
//
// 움직임(보기 좋으라고 넣은 것일 뿐, 자료는 건드리지 않는다): 열 때 카메라가 날아들고 지형이 솟는다, 손대기 전까지 천천히 돈다,
// 고른 경로 위로 빛이 가는 방향으로 흐른다, 우주인 자리에서 고리가 퍼진다. "움직임 줄이기"를 켠 기기에서는 전부 멈춘다.
//
// three.js는 이 파일을 열 때만 불러온다(ConsoleApp이 필요할 때 이 파일을 불러온다). 형(type) 정보는 받지 않았으므로 three의 것은 any로 다룬다.
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { Loader } from "../shared/Loader";
import { MAP_COLOR } from "../shared/MapView";
import type { Meta, XY } from "../shared/meta";
import type { ObsMark, Option, Stop } from "../types";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
interface HeightGrid { res_m: number; shape: [number, number]; extent_m: XY; z_min: number; z_max: number; heights: (number | null)[] }
interface Legend {
  name: string; note: string; kinds: Record<string, string>; ramp: { value: number; color: string }[];
  var_max: number; no_data_color: string; grade_bins: number[]; extent_m: XY;
}
type Kind = "off" | string;

const EXAG_CHOICES = [1, 2, 3, 5];    // 높이 과장의 선택지. 기본은 3배(2026-11-15: 2배로는 2D와 차이가 잘 안 보여 올렸다)
const EXAG_DEFAULT = 3;
const TEX_PX = 2048;                  // 지형에 입히는 그림의 한 변(px)
const SCIENCE_ALPHA = 0.78;           // 과학 가치 그림을 얹는 진하기 — 밑의 음영이 비쳐 굴곡이 보이게
const LAYER_ORDER = ["hillshade", "units", "minerals", "prior", "slope"];   // 2D 지도(MapView)와 같은 순서. 가림 레이어(링크, 그림자)는 그 위
const LIFT_M = 4;                     // 선과 표식을 지면에서 띄우는 높이(지형에 파묻혀 깜빡이지 않게)
const STEP_M = 20;                    // 선을 지형에 올려놓을 때 점을 찍는 간격(높이 격자의 칸과 같다)

// 높이 격자에서 (x, y) 자리의 높이를 읽는다(이웃한 네 점 사이를 고르게 잇는다). 격자점은 칸의 가운데에 있다
function heightAt(g: HeightGrid, x: number, y: number): number {
  const [rows, cols] = g.shape;
  const fc = Math.min(cols - 1, Math.max(0, x / g.res_m - 0.5)), fr = Math.min(rows - 1, Math.max(0, -y / g.res_m - 0.5));
  const c0 = Math.floor(fc), r0 = Math.floor(fr), c1 = Math.min(cols - 1, c0 + 1), r1 = Math.min(rows - 1, r0 + 1);
  const at = (r: number, c: number) => g.heights[r * cols + c] ?? g.z_min;
  const tx = fc - c0, ty = fr - r0;
  return (at(r0, c0) * (1 - tx) + at(r0, c1) * tx) * (1 - ty) + (at(r1, c0) * (1 - tx) + at(r1, c1) * tx) * ty;
}

// 글자 표식(늘 같은 크기로 화면을 본다)
function label(text: string, color: string): Any {
  const c = document.createElement("canvas"), pad = 10;
  const ctx = c.getContext("2d")!;
  ctx.font = "600 26px Inter Variable, system-ui, sans-serif";
  c.width = Math.ceil(ctx.measureText(text).width) + pad * 2; c.height = 40;
  ctx.font = "600 26px Inter Variable, system-ui, sans-serif";
  ctx.fillStyle = "rgba(4,4,5,0.82)"; ctx.fillRect(0, 0, c.width, c.height);
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.strokeRect(1, 1, c.width - 2, c.height - 2);
  ctx.fillStyle = color; ctx.textBaseline = "middle"; ctx.fillText(text, pad, c.height / 2 + 1);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, sizeAttenuation: false }));
  s.scale.set((c.width / c.height) * 0.034, 0.034, 1); s.renderOrder = 10;
  return s;
}

export default function Terrain3D(p: {
  meta: Meta; rev: number; layersOn: Record<string, boolean>; shadowBin: number; pos: XY | null; rover: XY | null; plan: Stop[]; route: XY[]; option: Option | null; obs: ObsMark[];
}) {
  const box = useRef<HTMLDivElement>(null);
  const three = useRef<Any>(null);                    // { scene, camera, renderer, controls, terrain, marks, draw }
  const [grid, setGrid] = useState<HeightGrid | null>(null);
  const [legend, setLegend] = useState<Legend | null>(null);
  const [failed, setFailed] = useState("");
  const [kind, setKind] = useState<Kind>("expected");
  const [exag, setExag] = useState(EXAG_DEFAULT);
  const [legendOpen, setLegendOpen] = useState(true);    // 범례의 긴 설명을 펼쳐 둘지(접어도 이름·색 눈금·등급 경계는 남는다)
  const pics = useRef(new Map<string, Promise<HTMLImageElement | null>>()).current;   // 받은 그림(타일, 과학 가치)을 주소로 기억해 둔다
  const still = useRef(typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches).current;
  const [spin, setSpin] = useState(!still);              // 천천히 도는 중인가. 사람이 지형을 잡으면 꺼진다

  // 재료 받기: 높이 격자(바뀌지 않는다)와 범례
  useEffect(() => {
    fetch("/console/height.json").then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then(setGrid).catch((e) => setFailed(`Terrain heights could not be loaded (${e}).`));
    fetch("/console/science_legend.json").then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then(setLegend).catch(() => undefined);
  }, []);

  // 장면 만들기: 지형, 빛, 카메라, 돌리기
  useEffect(() => {
    const el = box.current;
    if (!el || !grid) return undefined;
    const [rows, cols] = grid.shape, [W, H] = grid.extent_m;
    let renderer: Any;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); } catch { setFailed("This browser could not start 3D drawing (WebGL)."); return undefined; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x040405);
    const camera = new THREE.PerspectiveCamera(40, 1, 10, 40000);
    scene.fog = new THREE.FogExp2(0x040405, 0.00011);     // 먼 곳이 어둠에 잠겨 깊이가 보인다
    scene.add(new THREE.AmbientLight(0xffffff, 1.25));
    const sun = new THREE.DirectionalLight(0xffffff, 2.6); sun.position.set(-W, W * 0.42, -H * 0.3); scene.add(sun);   // 북서쪽 위에서 비춘다(음영 기복 지도의 관례)

    // 지형: 격자점마다 꼭짓점 하나. x = 동쪽, z = 남쪽(로컬 좌표의 −y), y = 높이(가장 낮은 곳이 0)
    const pos = new Float32Array(rows * cols * 3), uv = new Float32Array(rows * cols * 2), idx: number[] = [];
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const i = r * cols + c, x = (c + 0.5) * grid.res_m, z = (r + 0.5) * grid.res_m;
      pos.set([x, (grid.heights[i] ?? grid.z_min) - grid.z_min, z], i * 3);
      uv.set([x / W, 1 - z / H], i * 2);              // 그림을 입힐 자리. 범례가 오면 그 범위로 다시 맞춘다
      if (r < rows - 1 && c < cols - 1) idx.push(i, i + cols, i + 1, i + 1, i + cols, i + cols + 1);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
    geo.setIndex(idx); geo.computeVertexNormals();
    const terrain = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color: 0x8d8780 }));
    scene.add(terrain);
    // 옆면: 가장자리에서 아래로 벽을 내려 땅덩이 한 조각처럼 보이게 한다(지형과 같이 늘어난다). 그림일 뿐이다
    const BASE_M = 70, edge: number[][] = [[], [], [], []];
    for (let c = 0; c < cols; c++) { edge[0].push(c); edge[1].push((rows - 1) * cols + (cols - 1 - c)); }
    for (let r = 0; r < rows; r++) { edge[2].push((rows - 1 - r) * cols); edge[3].push(r * cols + cols - 1); }
    const wallPos: number[] = [], wallIdx: number[] = [];
    for (const side of edge) for (let k = 0; k < side.length; k++) {
      const i = side[k] * 3, n = wallPos.length / 3;
      wallPos.push(pos[i], pos[i + 1], pos[i + 2], pos[i], -BASE_M, pos[i + 2]);
      if (k < side.length - 1) wallIdx.push(n, n + 1, n + 2, n + 2, n + 1, n + 3);
    }
    const wallGeo = new THREE.BufferGeometry();
    wallGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(wallPos), 3)); wallGeo.setIndex(wallIdx); wallGeo.computeVertexNormals();
    terrain.add(new THREE.Mesh(wallGeo, new THREE.MeshLambertMaterial({ color: 0x2b2824, side: THREE.DoubleSide })));
    const marks = new THREE.Group(); scene.add(marks);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(W / 2, 0, H / 2);
    controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 150; controls.maxDistance = W * 2.6;
    controls.enableDamping = true; controls.dampingFactor = 0.07; controls.autoRotateSpeed = 0.55;   // 놓아도 살짝 더 미끄러진다
    camera.position.set(W / 2, W * 0.62, H * 1.28);   // 남쪽 위에서 북쪽을 내려다본다(2D 지도처럼 위가 북쪽)
    controls.update();

    // 그리기는 쉬지 않고 돈다(움직이는 것이 있어서). 한 장마다: 카메라, 지형 높이, 흐르는 빛, 퍼지는 고리
    const T: Any = { scene, camera, renderer, controls, terrain, marks, exagNow: still ? EXAG_DEFAULT : 0.05, exagTo: EXAG_DEFAULT, exagBuilt: EXAG_DEFAULT, fly: null, flow: [], flowOff: 0, pulse: [] };
    const draw = () => renderer.render(scene, camera);
    T.draw = draw;
    let raf = 0, last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      if (T.fly) {                                    // 처음 열 때 멀리서 날아든다
        const k = Math.min(1, (now - T.fly.t0) / T.fly.ms), e = 1 - (1 - k) ** 3;
        camera.position.lerpVectors(T.fly.from, T.fly.to, e);
        if (k >= 1) T.fly = null;
      }
      T.exagNow += (T.exagTo - T.exagNow) * Math.min(1, dt * 4.5);        // 높이는 목표 배율로 부드럽게 간다
      if (Math.abs(T.exagTo - T.exagNow) < 0.002) T.exagNow = T.exagTo;
      terrain.scale.y = T.exagNow; marks.scale.y = T.exagNow / T.exagBuilt;
      T.flowOff -= dt * 190; for (const m of T.flow) m.dashOffset = T.flowOff;                      // 빛이 길이 그려진 방향(출발 → 도착)으로 흐른다
      for (const r of T.pulse) { const u = ((now / 1000) * 0.55 + r.userData.ph) % 1; r.scale.setScalar(1 + u * 5); r.material.opacity = 0.7 * (1 - u); }
      controls.update(); draw();
      raf = requestAnimationFrame(tick);
    };
    controls.addEventListener("start", () => { T.fly = null; setSpin(false); });   // 사람이 잡으면 날아들기와 돌기를 멈춘다
    const fit = () => {
      const w = el.clientWidth, h = el.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
      marks.traverse((o: Any) => o.material?.resolution?.set(w, h));
      draw();
    };
    const ro = new ResizeObserver(fit); ro.observe(el); fit();
    if (still) { controls.addEventListener("change", draw); T.exagNow = EXAG_DEFAULT; terrain.scale.y = EXAG_DEFAULT; draw(); } else raf = requestAnimationFrame(tick);
    three.current = T;
    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); controls.dispose(); geo.dispose(); terrain.material.map?.dispose(); terrain.material.dispose(); renderer.dispose();
      renderer.domElement.remove(); three.current = null;
    };
  }, [grid]);

  // 지형에 입히는 그림: 왼쪽 LAYERS에서 켠 레이어를 2D와 같은 순서로 한 장에 겹쳐 그리고, 그 위에 과학 가치 그림을 얹는다.
  // 색은 타일과 그림에 칠해져 있는 그대로다 — 여기서 색을 정하지 않는다.
  const park = p.meta.rover_parks[0]?.id;
  const on = p.layersOn;
  const names = [...LAYER_ORDER.filter((k) => on[k] && !(k === "prior" && kind !== "off")),     // 과학 가치 그림을 켰으면 바탕 지도(prior) 타일은 겹치지 않게 뺀다
    ...(on.link ? [`link_${park}`] : []), ...(on.shadow ? [`shadow_${p.shadowBin}`] : [])];
  const texKey = JSON.stringify([names, kind, kind === "off" ? 0 : p.rev]);
  useEffect(() => {
    const t = three.current, info = p.meta.tiles;
    if (!t || !grid) return undefined;
    let gone = false;
    const pic = (url: string) => {
      if (!pics.has(url)) pics.set(url, new Promise((done) => { const im = new Image(); im.onload = () => done(im); im.onerror = () => done(null); im.src = url; }));
      return pics.get(url)!;
    };
    const cv = document.createElement("canvas"); cv.width = cv.height = TEX_PX;
    const ctx = cv.getContext("2d")!;
    (async () => {
      ctx.fillStyle = "#8d8780"; ctx.fillRect(0, 0, TEX_PX, TEX_PX);          // 아무 레이어도 안 켰을 때의 바탕색
      for (const name of names) {
        if (!info?.layers.some((l) => l.name === name)) continue;             // 번들에 없는 레이어는 건너뛴다
        const z = info.zoom_max, n = 2 ** z, px = TEX_PX / n;
        const tiles = await Promise.all(Array.from({ length: n * n }, (_, i) => pic(`/bundle/tiles/${name}/${z}/${i % n}/${Math.floor(i / n)}.png`)));
        if (gone) return;
        tiles.forEach((im, i) => { if (im) ctx.drawImage(im, (i % n) * px, Math.floor(i / n) * px, px, px); });
      }
      if (kind !== "off") {
        const im = await pic(`/console/science.png?kind=${kind}&v=${p.rev}`);
        if (gone) return;
        const ext = legend?.extent_m ?? grid.extent_m;                        // 과학 가치 그림의 범위는 범례가 알려 준다(지형보다 조금 클 수 있다)
        if (im) { ctx.globalAlpha = SCIENCE_ALPHA; ctx.imageSmoothingEnabled = false; ctx.drawImage(im, 0, 0, (TEX_PX * ext[0]) / grid.extent_m[0], (TEX_PX * ext[1]) / grid.extent_m[1]); ctx.globalAlpha = 1; }
      }
      if (gone || !three.current) return;
      const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
      const mat = t.terrain.material;
      mat.map?.dispose(); mat.map = tex; mat.color.set(0xffffff); mat.needsUpdate = true; t.draw();
    })();
    return () => { gone = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid, legend, texKey]);

  // 높이 과장과, 지형 위에 얹는 표식·선. 스냅샷은 초당 여러 번 오지만, 그릴 것이 실제로 바뀌었을 때만 다시 만든다
  const marksKey = JSON.stringify([p.pos, p.rover, p.plan, p.route.length, p.route[0], p.option?.digest, p.obs.length]);
  useEffect(() => {
    const t = three.current;
    if (!t || !grid) return;
    t.exagTo = exag; t.exagBuilt = exag; t.flow = []; t.pulse = [];
    if (still) { t.exagNow = exag; t.terrain.scale.y = exag; t.marks.scale.y = 1; }
    const g = t.marks;
    for (const o of [...g.children]) { g.remove(o); o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose(); }
    const at = (xy: XY, up = LIFT_M) => new THREE.Vector3(xy[0], (heightAt(grid, xy[0], xy[1]) - grid.z_min) * exag + up, -xy[1]);
    const size = new THREE.Vector2(); t.renderer.getSize(size);
    const line = (pts: XY[], color: string, width: number, flow = false) => {
      if (pts.length < 2) return;
      const flat: number[] = [];
      for (let i = 0; i < pts.length - 1; i++) {      // 꺾이는 점 사이에 점을 더 찍어 선이 지형을 따라가게 한다
        const a = pts[i], b = pts[i + 1], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / STEP_M));
        for (let k = i === 0 ? 0 : 1; k <= n; k++) { const v = at([a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n]); flat.push(v.x, v.y, v.z); }
      }
      const geo = new LineGeometry(); geo.setPositions(flat);
      const mat = new LineMaterial({ color: new THREE.Color(color).getHex(), linewidth: width, depthTest: false }); mat.resolution.set(size.x, size.y);
      const l = new Line2(geo, mat); l.renderOrder = 5; g.add(l);
      if (flow && !still) {                           // 같은 길 위에 짧은 밝은 토막을 띄엄띄엄 얹고, 그리는 동안 앞으로 민다
        const fm = new LineMaterial({ color: 0xeafff9, linewidth: width + 1, depthTest: false, dashed: true, dashSize: 26, gapSize: 150, transparent: true, opacity: 0.95 });
        fm.resolution.set(size.x, size.y);
        const fl = new Line2(geo, fm); fl.computeLineDistances(); fl.renderOrder = 6; g.add(fl); t.flow.push(fm);
      }
    };
    const pin = (xy: XY, color: string, text: string, r = 22, labelUp = 70) => {
      const m = new THREE.Mesh(new THREE.SphereGeometry(r, 20, 14), new THREE.MeshBasicMaterial({ color: new THREE.Color(color).getHex() }));
      m.position.copy(at(xy, r)); g.add(m);
      if (text) { const s = label(text, color); s.position.copy(at(xy, r * 2 + labelUp)); g.add(s); }
    };

    line(p.route, MAP_COLOR.route, 3);                                        // 다음에 갈 곳까지
    if (p.option) line(p.option.path as XY[], MAP_COLOR.preview, 4, true);          // 후보 표에서 고른 경로
    for (const o of p.obs) pin(o.xy as XY, o.found ? MAP_COLOR.found : MAP_COLOR.none, "", 12);
    const planned = new Set(p.plan.map((s) => s.poi_id).filter(Boolean));
    for (const q of p.meta.pois) pin(q.xy, planned.has(q.id) ? MAP_COLOR.stop : "#8f8a80", q.id, 18);   // 지점: 계획에 든 것은 흰색, 아닌 것은 흐리게
    for (const s of p.plan) if (s.purpose === "hyp_target") pin(s.xy as XY, MAP_COLOR.hyp, "Hypothesis target", 18);
    const stops = p.option?.stops.filter((s) => s.purpose === "hyp_target") ?? [];
    for (const s of stops) pin(s.xy as XY, MAP_COLOR.hyp, `Hypothesis target · ${p.option!.id}`, 18);
    if (p.rover) pin(p.rover, MAP_COLOR.back, "Rover", 26);
    if (p.pos) {
      pin(p.pos, MAP_COLOR.me, "Crew", 24, 190);     // 이름표를 더 높이 단다 — 로버 옆에 서 있을 때 두 이름표가 겹치지 않게
      if (!still) for (const ph of [0, 0.5]) {        // 우주인 자리에서 퍼지는 고리 둘
        const ring = new THREE.Mesh(new THREE.RingGeometry(30, 36, 48), new THREE.MeshBasicMaterial({ color: new THREE.Color(MAP_COLOR.me).getHex(), transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthTest: false }));
        ring.rotation.x = -Math.PI / 2; ring.position.copy(at(p.pos, LIFT_M + 2)); ring.userData.ph = ph; ring.renderOrder = 4; g.add(ring); t.pulse.push(ring);
      }
    }
    // 처음 한 번, 우주인이 있는 쪽을 가운데에 놓고 가까이서 본다(그 뒤로는 사람이 돌린 대로 둔다)
    const focus = p.pos ?? p.rover;
    if (!t.centered && focus) {
      const c = at(focus, 0);
      const to = new THREE.Vector3(c.x, c.y + 1050, c.z + 1650);   // 낮게 비스듬히 본다 — 위에서 내려다보면 2D와 다를 것이 없다
      t.controls.target.copy(c); t.centered = true;
      if (still) t.camera.position.copy(to);
      else { const from = new THREE.Vector3(c.x - 2600, c.y + 5200, c.z + 6400); t.camera.position.copy(from); t.fly = { from, to, t0: performance.now(), ms: 2400 }; }
      t.controls.update();
    }
    t.draw();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid, exag, marksKey]);

  useEffect(() => { if (three.current) three.current.controls.autoRotate = spin; }, [spin, grid]);

  if (failed) return <div className="terrain3d"><p className="none">{failed}</p></div>;
  const ramp = legend ? `linear-gradient(90deg, ${legend.ramp.map((s) => `${s.color} ${s.value * 100}%`).join(", ")})` : "";
  const top = kind === "var" ? legend?.var_max : 1;
  return (
    <div className="terrain3d">
      <div className="t3-view" ref={box}>{!grid && <Loader label="Loading terrain" />}</div>
      <div className="float t3-tools">
        <div className="row"><span className="lbl">Live science</span>
          <button type="button" className={kind === "off" ? "on" : ""} onClick={() => setKind("off")}>Off</button>
          {legend && Object.keys(legend.kinds).map((k) => <button type="button" key={k} className={kind === k ? "on" : ""} title={legend.kinds[k]} onClick={() => setKind(k)}>{k}</button>)}
        </div>
        <div className="row"><span className="lbl">Camera</span>
          <button type="button" className={spin ? "on" : ""} disabled={still} onClick={() => setSpin(!spin)} title="Turn slowly around the crew. Stops when you grab the terrain.">Orbit</button>
        </div>
        <div className="row"><span className="lbl">Height ×{exag}</span>
          {EXAG_CHOICES.map((v) => <button type="button" key={v} className={exag === v ? "on" : ""} onClick={() => setExag(v)}>×{v}</button>)}
          <small>Heights are stretched for viewing only.</small>
        </div>
      </div>
      {legend && kind !== "off" && (
        <div className="float t3-legend">
          <b>{legend.name} <button type="button" onClick={() => setLegendOpen(!legendOpen)} aria-expanded={legendOpen}>{legendOpen ? "Less" : "More"}</button></b>
          {legendOpen && <span>{legend.kinds[kind]}</span>}
          <i className="t3-ramp" style={{ background: ramp }}>
            {kind !== "var" && legend.grade_bins.map((v) => <u key={v} style={{ left: `${v * 100}%` }} title={`Grade boundary ${v.toFixed(3)}`} />)}
          </i>
          <span className="t3-ends"><em>0</em><em>{top}</em></span>
          <span className="t3-nodata"><i style={{ background: legend.no_data_color }} />No data</span>
          {/* 이 숫자가 무엇인지(보정된 확률이 아니라 상대 지수)는 접어도 늘 보인다 — 불확실성에 관한 말은 숨기지 않는다 */}
          <small>{legend.note}</small>
        </div>
      )}
      <div className="float t3-hint">Drag to rotate · right-drag to move · scroll to zoom</div>
    </div>
  );
}
