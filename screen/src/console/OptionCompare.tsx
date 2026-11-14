// 후보 옵션 비교 표와 고도 단면 (S3c §6.1, R-12, R-06).
//
// 표의 열은 카드의 칸과 같은 순서다. 정렬은 사람이 누른 열 하나 기준이고, 누르기 전에는 만들어진 순서다.
// 순위·종합 점수·추천 표시는 없다. "현장 표시"는 그 줄이 지금 현장 화면에 카드로 떠 있다는 사실만 알린다.
import { useState } from "react";
import { sortOptions } from "../shared/DecisionCards";
import { GRADE, LABEL, SORT, approx } from "../shared/i18n";
import { OPTION_COLOR } from "../shared/MapView";
import type { DecisionPoint, Option } from "../types";

type SortKey = DecisionPoint["sort_key"];
const COLS: [SortKey | null, string][] = [[null, "옵션"], ["time_min", "시간"], ["max_slope_deg", "경사(°)"], ["dose_uSv", "선량(µSv)"], ["value", "과학 가치"],
  [null, "분산"], ["info_gain", "정보 이득"], [null, "흔적"], [null, "두절(분)"], ["nlt_margin_min", "여유(분)"], [null, "귀환"]];

export function OptionCompare({ options, shownIds, picked, onPick }: { options: Option[]; shownIds: string[]; picked: string | null; onPick: (d: string | null) => void }) {
  const [sort, setSort] = useState<SortKey>("unsorted");
  if (options.length === 0) return <p className="none">아직 낸 결정 지점이 없습니다.</p>;
  return (
    <>
      <div className="sortline">정렬: {SORT[sort]} {sort !== "unsorted" && <button type="button" onClick={() => setSort("unsorted")}>정렬 풀기</button>}</div>
      <table className="compare">
        <thead><tr>{COLS.map(([k, name]) => <th key={name} className={k ? "sortable" : ""} onClick={() => k && setSort(k)}>{name}</th>)}</tr></thead>
        <tbody>
          {sortOptions(options, sort).map((o, i) => (
            <tr key={o.digest + i} className={picked === o.digest ? "picked" : ""} onClick={() => onPick(picked === o.digest ? null : o.digest)}>
              <td>{LABEL[o.label_key] ?? o.label_key}{o.from_hypothesis ? " · 가설" : ""}{shownIds.includes(o.digest) && <em className="shown">현장 표시</em>}</td>
              <td>{approx(o.time_min)}</td><td>{o.max_slope_deg}</td><td>{o.dose_uSv}</td>
              <td>{GRADE[o.value_grade]} ({o.value_lo === o.value_hi ? o.value_mean : `${o.value_lo}~${o.value_hi}`})</td>
              <td>{o.value_var}</td><td>{o.info_gain}</td><td>{o.explore_count}</td><td>{o.comm_loss_min}</td>
              <td>{o.late ? `늦음 ${o.nlt_margin_min}` : o.nlt_margin_min}</td><td>{approx(o.return_time_min)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

// 경로의 고도 단면: 프로그램이 실어 준 (누적 거리, 고도) 점을 그대로 잇는다
export function ElevationProfile({ o }: { o: Option }) {
  const pts = o.profile;
  if (pts.length < 2) return <p className="none">이 옵션은 걷는 구간이 없습니다(고도 단면 없음).</p>;
  const W = 420, H = 110, pad = 28;
  const xs = pts.map((p) => p[0]), zs = pts.map((p) => p[1]);
  const x1 = Math.max(...xs), z0 = Math.min(...zs), z1 = Math.max(...zs);
  const sx = (x: number) => pad + ((W - pad - 6) * x) / (x1 || 1);
  const sz = (z: number) => H - 18 - ((H - 30) * (z - z0)) / (z1 - z0 || 1);
  return (
    <svg className="profile" viewBox={`0 0 ${W} ${H}`}>
      <polyline fill="none" stroke={OPTION_COLOR[o.id] ?? "#e6e8eb"} strokeWidth="2" points={pts.map((p) => `${sx(p[0]).toFixed(1)},${sz(p[1]).toFixed(1)}`).join(" ")} />
      <text x={2} y={sz(z1) + 4}>{z1.toFixed(0)} m</text><text x={2} y={sz(z0) + 4}>{z0.toFixed(0)} m</text>
      <text x={pad} y={H - 4}>0</text><text x={W - 6} y={H - 4} textAnchor="end">{x1.toFixed(0)} m · {LABEL[o.label_key]}</text>
    </svg>
  );
}
