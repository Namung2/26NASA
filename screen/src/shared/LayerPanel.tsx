// 레이어 켜고 끄기 + 레이어별 출처 + 못 받은 레이어 (R-01, R-03).
// 범례의 색과 구간은 번들 메타(tiles.layers[].legend)에서 읽는다. 화면에 색을 따로 적지 않는다.
import { GRADE, LAYER, MINERAL } from "./i18n";
import type { LegendItem, Meta } from "./meta";

export const DEFAULT_LAYERS: Record<string, boolean> = { hillshade: true, slope: false, units: false, minerals: false, prior: false, link: true, shadow: false };

function legendText(x: LegendItem): string {
  if (x.grade) return GRADE[x.grade] ?? x.grade;
  if (x.key) return MINERAL[x.key] ?? (x.key === "no_link" ? "No link" : x.key === "shadow" ? "Shadow" : x.key);
  if (x.blocked) return `Over ${x.from}° (impassable)`;
  return `${x.from}~${x.to}°`;
}

export function LayerPanel({ meta, on, setOn, shadowBin, compact }: {
  meta: Meta; on: Record<string, boolean>; setOn: (v: Record<string, boolean>) => void; shadowBin: number; compact?: boolean;
}) {
  const park = meta.rover_parks[0]?.id;
  const tileName = (k: string) => (k === "link" ? `link_${park}` : k === "shadow" ? `shadow_${shadowBin}` : k);
  return (
    <div className="layers">
      {Object.keys(DEFAULT_LAYERS).map((k) => {
        const t = meta.tiles?.layers.find((x) => x.name === tileName(k));
        const src = meta.layers.find((x) => x.name === t?.source_layer)?.source;
        return (
          <div key={k} className="layer">
            <label title={src ? `Source: ${src.source} — ${src.product_id}\nLicense: ${src.license}` : ""}>
              <input type="checkbox" checked={!!on[k]} disabled={!t} onChange={(e) => setOn({ ...on, [k]: e.target.checked })} /> {LAYER[k]}
              {k === "shadow" && <small> {meta.shadow_bins_lmst[shadowBin]}~{meta.shadow_bins_lmst[shadowBin + 1]}</small>}
              {!t && <small> (missing)</small>}
            </label>
            {!compact && on[k] && t && t.legend.length > 0 && (
              <div className="legend">{t.legend.map((x, i) => <span key={i}><i style={{ background: x.color }} />{legendText(x)}</span>)}</div>
            )}
            {!compact && src && <div className="layer-src">{src.source} · {src.product_id}</div>}
          </div>
        );
      })}
      {meta.missing_layers.length > 0 && <div className="missing">Not received: {meta.missing_layers.join(", ")}</div>}
    </div>
  );
}
