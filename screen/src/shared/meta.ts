// 번들 메타(/bundle/meta.json). 한 지도 안에서는 바뀌지 않으므로 화면이 처음 뜰 때 한 번 읽는다(지도가 바뀌면 화면을 새로 연다 — 아래).
// 레이어·지점·바탕표·출처·임계값의 출처가 여기에 있다. 화면은 값을 지어내지 않고 여기 실린 것만 보인다.
import { useEffect, useState } from "react";

export type XY = [number, number];

export interface SourceRef { source: string; product_id: string; license: string; note: string; url: string | null }
export interface LegendItem { key?: string; code?: number; color: string; from?: number | null; to?: number | null; unit?: string; grade?: string; blocked?: boolean }
export interface TileLayerInfo { name: string; kind: string; source_layer: string; legend: LegendItem[]; park?: string; bin?: number }
export interface Param { key: string; value: unknown; unit: string; source: string; status: string }
export interface Poi { id: string; name: string; xy: XY; kind: string; value_mu: number | null; value_var: number | null; access_cost_min: number | null; source: SourceRef }
export interface Sample { id: string; name: string; xy: XY; lithology: string; organics: boolean | null; note: string; source: string }
export interface Meta {
  bundle_id: string;
  extent_m: XY;
  layers: { name: string; res_m: number; unit: string; source: SourceRef; registration: string }[];
  tiles?: { path: string; tile_px: number; zoom_min: number; zoom_max: number; extent_m: XY; layers: TileLayerInfo[] };
  pois: Poi[];
  samples: Sample[];
  rover_parks: { id: string; xy: XY }[];
  params: Param[];
  grade_bins: number[];
  shadow_bins_lmst: string[];
  missing_layers: string[];
  prior_values: { unit: string | null; mineral: string | null; mu: number; var: number }[];
  env?: { tau_kind?: string; tau_source?: string; radiation?: string };
}

export function useMeta(): Meta | null {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    fetch("/bundle/meta.json").then((r) => r.text()).then((t) => setMeta(JSON.parse(t.replace(/\bNaN\b/g, "null")) as Meta)).catch(() => setMeta(null));
  }, []);
  // 지도가 바뀌면 화면을 새로 연다. 첫 화면에서 다른 지도를 골라 시작하면 서버가 가리키는 번들이 바뀌는데, 이 화면은 번들 메타(지점, 타일, 범위)를
  // 처음 한 번만 읽기 때문에 그대로 두면 옛 지도의 지점 위에 새 지도의 자료를 그리게 된다. 시뮬레이터 서버(/sim/state)가 없으면 아무 일도 하지 않는다
  const id = meta?.bundle_id;
  useEffect(() => {
    if (!id) return undefined;
    const check = () => fetch("/sim/state").then((r) => (r.ok ? r.json() : null)).then((j: { bundle?: string } | null) => { if (j?.bundle && j.bundle !== id) window.location.reload(); }).catch(() => undefined);
    const timer = window.setInterval(check, 2000);
    return () => window.clearInterval(timer);
  }, [id]);
  return meta;
}

export function param(meta: Meta | null, key: string): Param | undefined {
  return meta?.params.find((p) => p.key === key);
}

// 메타의 값이 목록이면 글자("[100, 300, 1000]")로 실려 있다
export function paramList(meta: Meta | null, key: string): number[] {
  const v = param(meta, key)?.value;
  if (Array.isArray(v)) return v as number[];
  if (typeof v === "string") { try { return JSON.parse(v) as number[]; } catch { return []; } }
  return [];
}
