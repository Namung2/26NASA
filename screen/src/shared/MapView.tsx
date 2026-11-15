// 2D 지도 (S3c §6). 번들의 표시용 타일을 깔고, 스냅샷에 실려 온 것(위치·경로·흔적·관측·가설·옵션의 경로)을 그 위에 그린다.
//
// 좌표: 번들의 로컬 미터 좌표를 그대로 쓴다(x 동쪽, y 북쪽, 원점 = 구역의 북서쪽 모서리 → 구역 안의 y는 음수).
// Leaflet에는 [y, x] 순서로 넘긴다. 타일 약속은 pipeline/tiles.py의 머리말에 있다.
// 이 컴포넌트는 계산하지 않는다 — 받은 점을 그대로 찍는다.
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import type { HypView, ObsMark, Option, Stop, TraceMark } from "../types";
import { RULE } from "./i18n";
import type { Meta, XY } from "./meta";

export interface MapProps {
  meta: Meta;
  layersOn: Record<string, boolean>;       // LayerPanel의 켜고 끔 (hillshade, slope, units, minerals, prior, link, shadow)
  shadowBin: number;
  pos?: XY | null;
  sigma?: number;
  rover?: XY | null;
  route?: XY[];                             // 다음에 갈 곳까지
  back?: XY[];                              // 로버 귀환 경로
  track?: XY[];                             // 걸어온 길 (스냅샷에 실려 올 때만 그린다)
  visited?: Stop[];                         // 다녀온 지점 (스냅샷에 실려 올 때만 — 그 지점의 표식이 "다녀옴" 모양으로 바뀐다)
  plan?: Stop[];
  traces?: TraceMark[];
  obs?: ObsMark[];
  hyps?: HypView[];
  options?: Option[];                       // 떠 있는 카드(또는 콘솔에서 고른 후보)의 경로
  follow?: boolean;                         // 현재 위치를 따라간다
  onPickObs?: (id: string) => void;
  onPickHyp?: (id: string) => void;
  hideRoute?: boolean;                      // "다음에 갈 곳" 선을 잠깐 숨긴다 — 카드의 경로를 미리 보는 동안 두 선이 섞여 보이지 않게
  planning?: { candidates: { key: string; stop: Stop; label: string }[]; picked: string[]; onPick: (key: string) => void } | null;   // 경로 재설정: 누를 수 있는 정지점과, 지금까지 누른 순서
  shownHyp?: string | null;                 // 점선(방향·범위)을 보일 가설. 지도의 H 표식에 마우스를 올린 가설도 함께 보인다
}


// 지도 위의 선과 표식의 색. 범례(MapLegend)가 같은 값을 쓴다.
//
// 지도의 선은 네 가지다. 색뿐 아니라 굵기와 무늬도 서로 달라서, 둘이 같은 자리에 겹쳐도 둘 다 보인다.
//   걸어온 길     — 파란 가는 실선. 우주인이 실제로 지나온 자리 (track)
//   로버 귀환 경로 — 주황의 넓고 옅은 띠. 지금 자리에서 로버까지 (back)
//   다음에 갈 곳   — 흰 실선(어두운 테두리). 지금 자리에서 계획의 다음 지점까지 (route)
//   가설          — 노란 점선. 사람이 넣은 방향과 범위 (hyps). 평소에는 기준점의 H 표식만 있고, 그 표식이나
//                   "넣어 둔 가설" 목록의 항목에 마우스를 올렸을 때(누르면 계속)만 점선이 보인다 — 긴 선이 경로를 가리지 않게
// 다섯째로, 카드에 마우스를 올린 동안에만 그 카드의 경로가 미리 보인다(preview). 가는 방향으로 빛이 흐른다 — 모양은 style.css의 .flow.
export const MAP_COLOR = {
  me: "#5ab8ff",        // 현재 위치와 오차 원
  track: "#5ab8ff",     // 걸어온 길 (현재 위치와 같은 색 — 내가 지나온 자리)
  stop: "#ffffff",      // 가야 할 지점(P1·P2·…): 속 빈 고리
  done: "#5ab8ff",      // 다녀온 곳: 걸어온 길과 같은 색으로 속을 채운다 (지점이든 가설 목표든 같은 모양)
  route: "#ffffff",     // 다음에 갈 곳까지의 경로
  back: "#ff9f43",      // 로버까지의 귀환 경로, 로버
  hyp: "#ffd84d",       // 가설
  preview: "#35e0c2",   // 미리 보는 카드의 경로. 어느 카드든 같은 색이다 — 한 번에 하나만 보이고, 끝의 A·B·C 표식이 어느 카드인지 알린다
  trace: "#b79bff",     // 주의 흔적
  found: "#5fd38d",     // 관측: 발견
  none: "#aab2bd",      // 관측: 없음
  casing: "#07080a",    // 선 밑에 까는 어두운 테두리(밝은 지형 위에서도 선이 보이게)
};
const ll = (p: XY): L.LatLngExpression => [p[1], p[0]];

function dot(color: string, size = 12, text = "", cls = ""): L.DivIcon {
  return L.divIcon({ className: "", iconSize: [size, size], iconAnchor: [size / 2, size / 2],
    html: `<div class="mk ${cls}" style="width:${size}px;height:${size}px;${color ? `background:${color}` : ""}">${text}</div>` });
}

// 가야 할 곳의 표식(지점, 가설 목표). kind: "" = 지점(아직 안 감), "hyp" = 가설 목표(아직 안 감), "done" = 다녀옴
function stopIcon(text: string, kind: "" | "hyp" | "done"): L.DivIcon {
  return L.divIcon({ className: "", iconSize: [28, 28], iconAnchor: [14, 14], html: `<div class="mk stop ${kind}">${text}</div>` });
}

// 선 하나를 어두운 테두리와 함께 그린다
function line(g: L.LayerGroup, pts: L.LatLngExpression[], opt: L.PolylineOptions): L.Polyline {
  L.polyline(pts, { color: MAP_COLOR.casing, weight: (opt.weight ?? 3) + 3, opacity: 0.55, interactive: false }).addTo(g);
  return L.polyline(pts, opt).addTo(g);
}

// 지도 범례: 선과 표식이 무엇인지. 고정된 이름표일 뿐 값을 보지 않는다.
// track / back 은 그 화면이 그 선을 받아 그릴 때만 보인다(받지 않는 선을 범례에 적지 않는다)
export function MapLegend({ back = true, track = false }: { back?: boolean; track?: boolean }) {
  const ln = (c: string, dash?: string, w = 3, op = 1) => <svg width="26" height="10"><line x1="2" y1="5" x2="24" y2="5" stroke={c} strokeWidth={w} strokeOpacity={op} strokeDasharray={dash} strokeLinecap="round" /></svg>;
  const pt = (c: string) => <svg width="26" height="10"><circle cx="13" cy="5" r="4" fill={c} stroke="#07080a" /></svg>;
  return (
    <div className="float maplegend">
      {track && <span>{ln(MAP_COLOR.track, undefined, 2.5)}Path walked</span>}
      {back && <span>{ln(MAP_COLOR.back, undefined, 8, 0.5)}Return route to rover</span>}
      <span>{ln(MAP_COLOR.route)}Next leg</span>
      <span>{ln(MAP_COLOR.hyp, "1 6")}Hypothesis (hover H to show)</span>
      <span><svg width="26" height="12"><circle cx="13" cy="6" r="4.5" fill="none" stroke={MAP_COLOR.stop} strokeWidth="2.5" /></svg>Stop to visit</span>
      <span><svg width="26" height="12"><circle cx="13" cy="6" r="4.5" fill="none" stroke={MAP_COLOR.hyp} strokeWidth="2.5" /></svg>Hypothesis target</span>
      <span><svg width="26" height="12"><circle cx="13" cy="6" r="5.5" fill={MAP_COLOR.done} stroke="#07080a" /></svg>Visited</span>
      <span>{pt(MAP_COLOR.trace)}Attention trace</span>
      <span>{pt(MAP_COLOR.found)}Observation: found</span>
      <span>{pt(MAP_COLOR.none)}Observation: none</span>
    </div>
  );
}

export function MapView(p: MapProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const tiles = useRef<Record<string, L.TileLayer>>({});
  const dyn = useRef<L.LayerGroup | null>(null);
  const hypLines = useRef<L.LayerGroup | null>(null);
  const [hoverHyp, setHoverHyp] = useState<string | null>(null);   // 지도의 H 표식 위에 마우스가 올라가 있는 가설
  const me = useRef<{ marker: L.Marker; circle: L.Circle } | null>(null);
  const fixed = useRef<L.LayerGroup | null>(null);
  const picks = useRef({ obs: p.onPickObs, hyp: p.onPickHyp, plan: p.planning?.onPick });
  picks.current = { obs: p.onPickObs, hyp: p.onPickHyp, plan: p.planning?.onPick };
  const planLayer = useRef<L.LayerGroup | null>(null);
  const steady = useRef<{ back: L.Polyline; trackCase: L.Polyline; track: L.Polyline; routeCase: L.Polyline; route: L.Polyline } | null>(null);   // 늘 보이는 선 셋. 한 번 만들어 두고 점만 바꾼다

  // 지도 만들기 (한 번)
  useEffect(() => {
    if (!el.current || map.current) return;
    const ext = p.meta.extent_m[0];
    const crs = L.extend({}, L.CRS.Simple, { transformation: new L.Transformation(256 / ext, 0, -256 / ext, 0) });
    const m = L.map(el.current, { crs, minZoom: 0, maxZoom: 6, zoomSnap: 0.5, attributionControl: false,
      maxBounds: [[-ext * 1.2, -ext * 0.2], [ext * 0.2, ext * 1.2]] });
    m.fitBounds([[-ext, 0], [0, ext]]);
    map.current = m;
    fixed.current = L.layerGroup().addTo(m);
    hypLines.current = L.layerGroup().addTo(m);
    // 늘 보이는 선(귀환 경로, 걸어온 길, 다음에 갈 곳)은 한 번 만들어 두고 점만 갈아 끼운다. 걸을 때마다(몇 초에 한 번) 걸어온 길에 점이 늘고
    // 귀환 경로가 바뀌는데, 그때마다 지도 위의 것을 전부 지웠다 다시 그리면 화면이 깜빡이고 흐르는 빛도 처음부터 다시 시작한다
    const lines = L.layerGroup().addTo(m);
    const casing = (w: number) => L.polyline([], { color: MAP_COLOR.casing, weight: w + 3, opacity: 0.55, interactive: false });
    steady.current = {
      back: L.polyline([], { color: MAP_COLOR.back, weight: 9, opacity: 0.5, lineCap: "round", lineJoin: "round" }).bindTooltip("Return route to rover").addTo(lines),
      trackCase: casing(2.5).addTo(lines),
      track: L.polyline([], { color: MAP_COLOR.track, weight: 2.5, opacity: 0.95 }).bindTooltip("Path walked").addTo(lines),
      routeCase: casing(3).addTo(lines),
      route: L.polyline([], { color: MAP_COLOR.route, weight: 3, opacity: 1 }).bindTooltip("Route to the next stop").addTo(lines),
    };
    dyn.current = L.layerGroup().addTo(m);
    planLayer.current = L.layerGroup().addTo(m);
    L.control.scale({ imperial: false }).addTo(m);
    // 결정 지점 카드가 뜨고 내려가면 지도 칸의 크기가 바뀐다 — 그때마다 지도에 알려 빈 띠가 생기지 않게 한다
    const ro = new ResizeObserver(() => m.invalidateSize({ animate: false }));
    ro.observe(el.current);
    return () => { ro.disconnect(); m.remove(); map.current = null; tiles.current = {}; me.current = null; steady.current = null; };
  }, [p.meta]);

  // 타일 레이어 켜고 끄기
  const park = p.meta.rover_parks[0]?.id;
  const wanted: Record<string, boolean> = {
    hillshade: !!p.layersOn.hillshade, slope: !!p.layersOn.slope, units: !!p.layersOn.units, minerals: !!p.layersOn.minerals,
    prior: !!p.layersOn.prior, [`link_${park}`]: !!p.layersOn.link, [`shadow_${p.shadowBin}`]: !!p.layersOn.shadow,
  };
  const wantedKey = JSON.stringify(wanted);
  useEffect(() => {
    const m = map.current, info = p.meta.tiles;
    if (!m || !info) return;
    const ext = p.meta.extent_m[0];
    const order = ["hillshade", "units", "minerals", "prior", "slope"];
    for (const lay of info.layers) {
      const on = !!wanted[lay.name];
      let t = tiles.current[lay.name];
      if (on && !t) {
        t = L.tileLayer(`/bundle/tiles/${lay.name}/{z}/{x}/{y}.png`, { minZoom: 0, maxZoom: 6, maxNativeZoom: info.zoom_max, tileSize: info.tile_px,
          bounds: [[-ext, 0], [0, ext]], noWrap: true, zIndex: 10 + Math.max(0, order.indexOf(lay.name)) + (lay.kind === "mask" ? 10 : 0) });
        tiles.current[lay.name] = t;
      }
      if (t) { if (on && !m.hasLayer(t)) t.addTo(m); if (!on && m.hasLayer(t)) m.removeLayer(t); }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantedKey, p.meta]);

  // 바뀌지 않는 것: 지점(POI), 선행 시료 지점, 로버
  useEffect(() => {
    const g = fixed.current;
    if (!g) return;
    g.clearLayers();
    for (const s of p.meta.samples ?? [])
      L.marker(ll(s.xy), { icon: dot("", 8, "", "sample"), interactive: true }).bindTooltip(`Earlier sample ${s.name}<br>${s.lithology}`).addTo(g);
    // 가야 할 곳의 표식은 한 가지 모양이다: 아직 안 간 곳은 속 빈 고리(지점은 흰색, 가설 목표는 가설의 노란색),
    // 다녀온 곳은 같은 크기의 채워진 원(걸어온 길의 파란색). 다녀왔는지는 화면이 따지지 않고 스냅샷의 visited에 실려 온 것만 본다
    const seen = new Set((p.visited ?? []).map((v) => v.poi_id).filter(Boolean));
    for (const q of p.meta.pois) {
      const done = seen.has(q.id);
      L.marker(ll(q.xy), { icon: stopIcon(q.id, done ? "done" : "") }).bindTooltip(`${q.name}${done ? " · visited" : ""} · value ${q.value_mu ?? "–"} (variance ${q.value_var ?? "–"})`).addTo(g);
    }
    for (const v of p.visited ?? []) {
      if (v.poi_id || v.purpose !== "hyp_target") continue;
      L.marker(ll(v.xy as XY), { icon: stopIcon("✓", "done") }).bindTooltip("Hypothesis target · visited", { permanent: true, direction: "right", offset: [13, 0], className: "maplabel done" }).addTo(g);
    }
    if (p.rover) L.marker(ll(p.rover), { icon: L.divIcon({ className: "", iconSize: [26, 26], iconAnchor: [13, 13], html: `<div class="mk rover" style="background:${MAP_COLOR.back}">R</div>` }) }).bindTooltip("Rover").addTo(g);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.meta, p.rover?.[0], p.rover?.[1], JSON.stringify(p.visited ?? [])]);

  // 스냅샷에 따라 바뀌는 것. 내용이 같으면 다시 그리지 않는다(열어 둔 설명이 닫히지 않게)
  // 늘 보이는 선 셋의 점 갈아 끼우기 (그리는 순서 = 아래에서 위로: 귀환 경로의 넓은 띠 → 걸어온 길 → 다음에 갈 곳).
  // 귀환 경로는 넓고 옅은 띠라서, 다음에 갈 곳이 로버일 때(프로그램이 두 선을 같은 길로 보낸다 — device/node.py)에도 띠 위에 흰 선이 얹혀 둘 다 보인다
  const steadyKey = JSON.stringify([p.hideRoute, p.route, p.back, p.track?.length, p.track?.[p.track.length - 1]]);
  useEffect(() => {
    const st = steady.current;
    if (!st) return;
    const pts = (a?: XY[]) => (a && a.length > 1 ? a.map(ll) : []);
    st.back.setLatLngs(pts(p.back));
    st.trackCase.setLatLngs(pts(p.track)); st.track.setLatLngs(pts(p.track));
    const route = p.hideRoute ? [] : pts(p.route);
    st.routeCase.setLatLngs(route); st.route.setLatLngs(route);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steadyKey, p.meta]);

  // 주의 흔적의 옅어짐(fade)은 쉬지 않고 조금씩 바뀐다 — 눈에 보일 만큼(1/10) 바뀌었을 때만 다시 그린다
  const dynKey = JSON.stringify([p.plan, p.traces?.map((t) => [t.xy, t.kind, t.kept, Math.round(t.fade * 10)]), p.obs, p.hyps, p.options?.map((o) => [o.id, o.path, o.stops, o.hyp_ids])]);
  useEffect(() => {
    const g = dyn.current;
    if (!g) return;
    g.clearLayers();
    // 늘 보이는 선 셋(귀환 경로, 걸어온 길, 다음에 갈 곳)은 여기서 그리지 않는다 — 위의 따로 된 그리기가 점만 바꾼다
    for (const o of p.options ?? []) {
      if (o.path.length < 2) continue;
      const c = MAP_COLOR.preview, pts = o.path.map((q) => ll(q as XY));
      line(g, pts, { color: c, weight: 4, opacity: 0.95 });
      // 가는 방향을 알리는 빛: 같은 길 위에 점선 두 겹(번짐 + 알맹이)을 얹고, CSS가 점선을 출발 → 도착 쪽으로 흘린다
      L.polyline(pts, { className: "flow flow-glow", color: c, weight: 11, opacity: 0.45, interactive: false }).addTo(g);
      L.polyline(pts, { className: "flow", color: "#ffffff", weight: 4.5, opacity: 1, interactive: false }).addTo(g);
      L.marker(pts[pts.length - 1], { icon: dot(c, 22, o.id, "opt") }).addTo(g);
      // 경로의 시작점 = 이 카드를 계산한 자리. 카드가 떠 있는 동안 걸으면 현재 위치와 벌어지므로, 선이 어디서 출발하는지 이름표로 알린다
      L.marker(pts[0], { icon: L.divIcon({ className: "", iconSize: [14, 14], iconAnchor: [7, 7], html: `<div class="mk from" style="border-color:${c}"></div>` }), zIndexOffset: -200, interactive: false })
        .bindTooltip("Where the cards were computed", { permanent: true, direction: "left", offset: [-10, 0], className: "maplabel from" }).addTo(g);
    }
    // 가설 목표: 가설의 점선(사람이 넣은 방향·범위)과 실제로 가게 되는 자리는 다르다. 목표는 코어가 그 선 근처에서
    // 값이 가장 많이 오르고 걸어갈 수 있는 칸으로 고르고, 출발 한계에 안 맞으면 범위를 줄여 잡기 때문이다(core/src/decision.cpp).
    // 그래서 목표 자리를 고리와 이름표로 따로 표시한다. 가설의 기준점과 잇는 선은 그리지 않는다 — 가설의 점선과 겹쳐 보기 어려웠다.
    // 화면은 받은 정지점을 찍을 뿐이다 — 목표를 스스로 찾거나 가설과 짝을 지어 보지 않는다
    const hypTarget = (xy: XY, from: string) => L.marker(ll(xy), { icon: stopIcon("", "hyp"), zIndexOffset: -100 })
      .bindTooltip(`Hypothesis target${from}`, { permanent: true, direction: "right", offset: [13, 0], className: "maplabel" }).addTo(g);
    // 이미 계획에 들어 있는 가설 목표는 아래에서 한 번만 표시한다(카드의 정지점에 같은 자리가 또 실려 와도 이름표를 겹쳐 찍지 않는다)
    const inPlan = new Set((p.plan ?? []).filter((x) => x.purpose === "hyp_target").map((x) => x.xy.join(",")));
    for (const o of p.options ?? []) {
      for (const st of o.stops) {
        if (st.purpose !== "hyp_target" || inPlan.has(st.xy.join(","))) continue;
        hypTarget(st.xy as XY, ` · card ${o.id}`);
      }
    }
    for (const s of p.plan ?? []) {
      if (s.poi_id) continue;
      if (s.purpose === "hyp_target") hypTarget(s.xy as XY, "");
      else L.circleMarker(ll(s.xy as XY), { radius: 8, color: MAP_COLOR.route, weight: 2, fillColor: MAP_COLOR.casing, fillOpacity: 0.35 }).bindTooltip(s.purpose === "rover" ? "Rover" : "Stop").addTo(g);
    }
    for (const t of p.traces ?? [])
      L.circleMarker(ll(t.xy as XY), { radius: t.kind === "photo" ? 5 : 4, color: MAP_COLOR.trace, weight: t.kept ? 3 : 1, fillColor: MAP_COLOR.trace, fillOpacity: 0.15 + 0.6 * t.fade, opacity: 0.3 + 0.7 * t.fade })
        .bindTooltip(t.kind === "photo" ? "Attention trace: photo" : "Attention trace: mention").addTo(g);
    for (const o of p.obs ?? []) {
      const mk = L.marker(ll(o.xy as XY), { icon: dot(o.found ? MAP_COLOR.found : MAP_COLOR.none, 16, o.found ? "✓" : "–") })
        .bindTooltip(`${o.found ? "Found" : "None"}${o.confirmed ? " · re-checked" : ""}${o.note ? `<br>Note: ${escapeHtml(o.note)}` : ""}`);
      mk.on("click", () => picks.current.obs?.(o.id));
      mk.addTo(g);
    }
    for (const h of p.hyps ?? []) {
      const tip = `Hypothesis ${h.hyp_id} · ${RULE[h.rule] ?? h.rule}<br>At entry: ${h.conf_chosen_name} → now: ${h.conf_now_name} (${h.n_used} confirmed observations)`;
      // 기준점의 표식만 늘 그린다. 방향·범위의 점선은 아래의 따로 된 그리기에서, 올리거나 고른 가설 것만 그린다
      const mk = L.marker(ll(h.xy as XY), { icon: dot(MAP_COLOR.hyp, 18, "H") }).bindTooltip(tip);
      mk.on("click", () => picks.current.hyp?.(h.hyp_id));
      mk.on("mouseover", () => setHoverHyp(h.hyp_id));
      mk.on("mouseout", () => setHoverHyp(null));
      mk.addTo(g);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dynKey]);

  // 가설의 점선: 마우스를 올린 가설(지도의 H 표식)과 밖에서 정해 준 가설(목록에서 올리거나 누른 것)만 그린다
  const hypKey = JSON.stringify([hoverHyp, p.shownHyp, p.hyps]);
  useEffect(() => {
    const g = hypLines.current;
    if (!g) return;
    g.clearLayers();
    for (const h of p.hyps ?? []) {
      if (h.hyp_id !== hoverHyp && h.hyp_id !== p.shownHyp) continue;
      if (h.rule === "proximity") {                 // 근접 군집은 방향이 없다 — 범위를 원으로
        L.circle(ll(h.xy as XY), { radius: h.extent_m, color: MAP_COLOR.hyp, weight: 2, dashArray: "1 7", lineCap: "round", fillOpacity: 0.05, interactive: false }).addTo(g);
        continue;
      }
      const th = (h.direction_deg * Math.PI) / 180;
      const end: XY = [h.xy[0] + Math.sin(th) * h.extent_m, h.xy[1] + Math.cos(th) * h.extent_m];
      line(g, [ll(h.xy as XY), ll(end)], { color: MAP_COLOR.hyp, weight: 3, dashArray: "1 7", lineCap: "round", interactive: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hypKey]);

  // 현재 위치와 오차 원
  useEffect(() => {
    const m = map.current;
    if (!m || !p.pos) return;
    if (!me.current) {
      me.current = {
        circle: L.circle(ll(p.pos), { radius: Math.max(1, p.sigma ?? 0), color: MAP_COLOR.me, weight: 1, fillOpacity: 0.15 }).addTo(m),
        marker: L.marker(ll(p.pos), { icon: L.divIcon({ className: "", iconSize: [20, 20], iconAnchor: [10, 10], html: `<div class="mk me" style="background:${MAP_COLOR.me};color:${MAP_COLOR.me}"></div>` }), zIndexOffset: 1000 }).bindTooltip("Current position").addTo(m),
      };
      m.setView(ll(p.pos), 3, { animate: false });
    }
    me.current.marker.setLatLng(ll(p.pos));
    me.current.circle.setLatLng(ll(p.pos)).setRadius(Math.max(1, p.sigma ?? 0));
    if (p.follow && !p.planning && !m.getBounds().pad(-0.25).contains(ll(p.pos))) m.panTo(ll(p.pos));   // 순서를 짜는 동안에는 지도를 끌고 가지 않는다
  }, [p.pos?.[0], p.pos?.[1], p.sigma, p.follow]);

  // 경로 재설정(사람이 정지점 순서를 직접 짠다). 누를 수 있는 정지점에 고리를 얹고, 누른 순서대로 번호를 매겨 흐르는 선으로 잇는다.
  // 이 선은 "순서"만 보인다(곧은 선) — 실제로 걷는 길과 시간·경사는 보낸 뒤 로버가 계산해 카드로 돌려준다. 화면은 순서를 모을 뿐이다
  const planKey = JSON.stringify([p.planning?.candidates.map((c) => [c.key, c.stop.xy]), p.planning?.picked, p.planning ? p.pos : null]);
  useEffect(() => {
    const g = planLayer.current;
    if (!g) return;
    g.clearLayers();
    const pl = p.planning;
    if (!pl) return;
    const at = new Map(pl.candidates.map((c) => [c.key, c]));
    const chain = [...(p.pos ? [ll(p.pos)] : []), ...pl.picked.map((k) => at.get(k)).filter((c): c is NonNullable<typeof c> => !!c).map((c) => ll(c.stop.xy as XY))];
    if (chain.length > 1) {
      const c = MAP_COLOR.preview;
      line(g, chain, { color: c, weight: 3, opacity: 0.9, dashArray: "2 7" });
      L.polyline(chain, { className: "flow flow-glow", color: c, weight: 11, opacity: 0.45, interactive: false }).addTo(g);
      L.polyline(chain, { className: "flow", color: "#ffffff", weight: 4.5, opacity: 1, interactive: false }).addTo(g);
    }
    for (const c of pl.candidates) {
      const n = pl.picked.indexOf(c.key);
      const icon = L.divIcon({ className: "", iconSize: [40, 40], iconAnchor: [20, 20], html: `<div class="mk plan${n >= 0 ? " picked" : ""}">${n >= 0 ? n + 1 : "+"}</div>` });
      const mk = L.marker(ll(c.stop.xy as XY), { icon, zIndexOffset: 2000 }).bindTooltip(n >= 0 ? `${c.label} — stop ${n + 1}. Click to take it out` : `${c.label} — click to add as the next stop`);
      mk.on("click", () => picks.current.plan?.(c.key));
      mk.addTo(g);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planKey]);
  // 순서 짜기를 시작하면 누를 수 있는 정지점과 현재 위치가 한눈에 들어오게 지도를 맞춘다(오른쪽의 창에 가리지 않게 여백을 둔다)
  const planningOn = !!p.planning;
  useEffect(() => {
    const m = map.current, pl = p.planning;
    if (!m || !pl || pl.candidates.length === 0) return;
    const pts = [...pl.candidates.map((c) => ll(c.stop.xy as XY)), ...(p.pos ? [ll(p.pos)] : [])];
    m.fitBounds(L.latLngBounds(pts), { paddingTopLeft: [60, 50], paddingBottomRight: [Math.min(470, m.getSize().x * 0.45), 50], maxZoom: 4 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planningOn]);

  return <div ref={el} className="map" />;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}
