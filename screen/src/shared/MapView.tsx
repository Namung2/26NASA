// 2D 지도 (S3c §6). 번들의 표시용 타일을 깔고, 스냅샷에 실려 온 것(위치·경로·흔적·관측·가설·옵션의 경로)을 그 위에 그린다.
//
// 좌표: 번들의 로컬 미터 좌표를 그대로 쓴다(x 동쪽, y 북쪽, 원점 = 구역의 북서쪽 모서리 → 구역 안의 y는 음수).
// Leaflet에는 [y, x] 순서로 넘긴다. 타일 약속은 pipeline/tiles.py의 머리말에 있다.
// 이 컴포넌트는 계산하지 않는다 — 받은 점을 그대로 찍는다.
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
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
  route?: XY[];
  back?: XY[];
  plan?: Stop[];
  traces?: TraceMark[];
  obs?: ObsMark[];
  hyps?: HypView[];
  options?: Option[];                       // 떠 있는 카드(또는 콘솔에서 고른 후보)의 경로
  follow?: boolean;                         // 현재 위치를 따라간다
  onPickObs?: (id: string) => void;
  onPickHyp?: (id: string) => void;
}

// 옵션 이름표(A·B·C)마다 고정된 선 색. 값의 크고 작음과 무관하다 — 어느 선이 어느 카드인지 가르는 용도일 뿐이다
export const OPTION_COLOR: Record<string, string> = { A: "#4cc9f0", B: "#f9c74f", C: "#f28482" };
const ll = (p: XY): L.LatLngExpression => [p[1], p[0]];

function dot(color: string, size = 12, text = ""): L.DivIcon {
  return L.divIcon({ className: "", iconSize: [size, size], iconAnchor: [size / 2, size / 2],
    html: `<div class="mk" style="width:${size}px;height:${size}px;background:${color}">${text}</div>` });
}

export function MapView(p: MapProps) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const tiles = useRef<Record<string, L.TileLayer>>({});
  const dyn = useRef<L.LayerGroup | null>(null);
  const me = useRef<{ marker: L.Marker; circle: L.Circle } | null>(null);
  const fixed = useRef<L.LayerGroup | null>(null);
  const picks = useRef({ obs: p.onPickObs, hyp: p.onPickHyp });
  picks.current = { obs: p.onPickObs, hyp: p.onPickHyp };

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
    dyn.current = L.layerGroup().addTo(m);
    L.control.scale({ imperial: false }).addTo(m);
    return () => { m.remove(); map.current = null; tiles.current = {}; me.current = null; };
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
      L.marker(ll(s.xy), { icon: dot("#8d99ae", 8), interactive: true }).bindTooltip(`선행 시료 ${s.name}<br>${s.lithology}`).addTo(g);
    for (const q of p.meta.pois)
      L.marker(ll(q.xy), { icon: dot("#ffffff", 18, q.id.replace(/^P/, "")) }).bindTooltip(`${q.name} · 가치 ${q.value_mu ?? "–"} (분산 ${q.value_var ?? "–"})`).addTo(g);
    if (p.rover) L.marker(ll(p.rover), { icon: L.divIcon({ className: "", iconSize: [22, 22], iconAnchor: [11, 11], html: `<div class="mk rover">R</div>` }) }).bindTooltip("로버").addTo(g);
  }, [p.meta, p.rover?.[0], p.rover?.[1]]);

  // 스냅샷에 따라 바뀌는 것. 내용이 같으면 다시 그리지 않는다(열어 둔 설명이 닫히지 않게)
  const dynKey = JSON.stringify([p.route, p.back, p.plan, p.traces, p.obs, p.hyps, p.options?.map((o) => [o.id, o.path])]);
  useEffect(() => {
    const g = dyn.current;
    if (!g) return;
    g.clearLayers();
    if (p.back && p.back.length > 1) L.polyline(p.back.map(ll), { color: "#ff8fab", weight: 3, dashArray: "6 8", opacity: 0.9 }).bindTooltip("로버까지의 귀환 경로").addTo(g);
    for (const o of p.options ?? []) {
      if (o.path.length < 2) continue;
      const c = OPTION_COLOR[o.id] ?? "#ffffff";
      L.polyline(o.path.map((q) => ll(q as XY)), { color: c, weight: 4, opacity: 0.85 }).addTo(g);
      L.marker(ll(o.path[o.path.length - 1] as XY), { icon: dot(c, 20, o.id) }).addTo(g);
    }
    if (p.route && p.route.length > 1) L.polyline(p.route.map(ll), { color: "#ffffff", weight: 3, opacity: 0.95 }).bindTooltip("다음 지점까지의 경로").addTo(g);
    for (const s of p.plan ?? []) if (!s.poi_id) L.circleMarker(ll(s.xy as XY), { radius: 7, color: "#ffffff", weight: 2, fillOpacity: 0 }).bindTooltip(s.purpose === "hyp_target" ? "가설 목표" : s.purpose === "rover" ? "로버" : "정지점").addTo(g);
    for (const t of p.traces ?? [])
      L.circleMarker(ll(t.xy as XY), { radius: t.kind === "photo" ? 5 : 4, color: "#b388ff", weight: t.kept ? 3 : 1, fillColor: "#b388ff", fillOpacity: 0.15 + 0.6 * t.fade, opacity: 0.3 + 0.7 * t.fade })
        .bindTooltip(t.kind === "photo" ? "주의 흔적: 촬영" : "주의 흔적: 언급").addTo(g);
    for (const o of p.obs ?? []) {
      const mk = L.marker(ll(o.xy as XY), { icon: dot(o.found ? "#80ed99" : "#adb5bd", 14, o.found ? "✓" : "–") })
        .bindTooltip(`${o.found ? "발견" : "없음"}${o.confirmed ? " · 다시 확인함" : ""}${o.note ? `<br>메모: ${escapeHtml(o.note)}` : ""}`);
      mk.on("click", () => picks.current.obs?.(o.id));
      mk.addTo(g);
    }
    for (const h of p.hyps ?? []) {
      const th = (h.direction_deg * Math.PI) / 180;
      const end: XY = [h.xy[0] + Math.sin(th) * h.extent_m, h.xy[1] + Math.cos(th) * h.extent_m];
      const tip = `가설 ${h.hyp_id} · ${RULE[h.rule] ?? h.rule}<br>처음: ${h.conf_chosen_name} → 지금: ${h.conf_now_name} (확인된 관측 ${h.n_used}건)`;
      if (h.rule !== "proximity") L.polyline([ll(h.xy as XY), ll(end)], { color: "#ffd166", weight: 3, dashArray: "2 6" }).bindTooltip(tip).addTo(g);
      else L.circle(ll(h.xy as XY), { radius: h.extent_m, color: "#ffd166", weight: 2, dashArray: "2 6", fillOpacity: 0.04 }).bindTooltip(tip).addTo(g);
      const mk = L.marker(ll(h.xy as XY), { icon: dot("#ffd166", 14, "H") }).bindTooltip(tip);
      mk.on("click", () => picks.current.hyp?.(h.hyp_id));
      mk.addTo(g);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dynKey]);

  // 현재 위치와 오차 원
  useEffect(() => {
    const m = map.current;
    if (!m || !p.pos) return;
    if (!me.current) {
      me.current = {
        circle: L.circle(ll(p.pos), { radius: Math.max(1, p.sigma ?? 0), color: "#4ea8de", weight: 1, fillOpacity: 0.15 }).addTo(m),
        marker: L.marker(ll(p.pos), { icon: L.divIcon({ className: "", iconSize: [18, 18], iconAnchor: [9, 9], html: `<div class="mk me"></div>` }), zIndexOffset: 1000 }).bindTooltip("현재 위치").addTo(m),
      };
      m.setView(ll(p.pos), 3, { animate: false });
    }
    me.current.marker.setLatLng(ll(p.pos));
    me.current.circle.setLatLng(ll(p.pos)).setRadius(Math.max(1, p.sigma ?? 0));
    if (p.follow && !m.getBounds().pad(-0.25).contains(ll(p.pos))) m.panTo(ll(p.pos));
  }, [p.pos?.[0], p.pos?.[1], p.sigma, p.follow]);

  return <div ref={el} className="map" />;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}
