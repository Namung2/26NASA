// 옵션 카드 (S3c §6.2, §6.3 — R-52).
//
// 금지 규칙: 옵션 카드는 이 컴포넌트 하나뿐이고, 카드의 크기·색·테두리·순서를 바꾸는 prop이 없다.
// 가설에서 나온 옵션도, 알고리즘이 낸 옵션도, 귀환 옵션도 같은 칸을 같은 순서로 보인다.
// 값끼리 견줘 색을 입히지 않는다. 안전 임계 표시는 옵션에 실려 온 over_limit 목록을 그대로 그릴 뿐이다.
// 칸의 순서(고정): 이름표 → 종류 → 시간 → 최대 경사 → 선량 → 과학 가치(등급 + 범위) → 분산 → 정보 이득 →
//                 흔적을 남긴 곳 → 통신 두절 예상 → 출발 한계 여유 → 귀환 비용 → 근거
import type { Option } from "../types";
import { BINDING, GRADE, KIND, LABEL, OVER, approx } from "./i18n";
import type { Meta } from "./meta";
import { SourceTip } from "./SourceTip";

export function OptionCard({ o, meta, text, onChoose }: { o: Option; meta: Meta | null; text?: string; onChoose?: () => void }) {
  const range = o.value_lo === o.value_hi ? `${o.value_mean}` : `${o.value_lo}~${o.value_hi}`;
  return (
    <div className="card" data-option={o.id}>
      <div className="card-head">
        <span className="card-id">{o.id}</span>
        <span className="card-label">{LABEL[o.label_key] ?? o.label_key}</span>
        <span className="card-kind">{KIND[o.kind]}{o.from_hypothesis ? " · from hypothesis" : ""}{o.prior_only ? " · prior map only" : ""}</span>
      </div>
      <dl>
        <dt>Time</dt><dd>{approx(o.time_min)}</dd>
        <dt>Max slope <SourceTip meta={meta} k="mobility.theta_max_deg" /></dt><dd>{o.max_slope_deg}°{o.over_limit.includes("max_slope_deg") && <em className="over">{OVER.max_slope_deg}</em>}</dd>
        <dt>Dose <SourceTip meta={meta} k="radiation.dose_rate_mSv_day" /></dt><dd>{o.dose_uSv} µSv{o.over_limit.includes("dose_uSv") && <em className="over">{OVER.dose_uSv}</em>}</dd>
        <dt>Science</dt><dd>{GRADE[o.value_grade]} ({range})</dd>
        <dt>Variance</dt><dd>{o.value_var}</dd>
        <dt>Info gain</dt><dd>{o.info_gain}</dd>
        <dt>Traces</dt><dd>{o.explore_count}</dd>
        <dt>Comm loss</dt><dd>{o.comm_loss_min} min</dd>
        <dt>Margin <SourceTip meta={meta} k="suit.eva_max_h" /></dt>
        <dd>{o.late ? `Late — ${Math.abs(o.nlt_margin_min)} min past limit` : `${o.nlt_margin_min} min`} <small>({BINDING[o.nlt_binding]})</small></dd>
        <dt>Return</dt><dd>{approx(o.return_time_min)}</dd>
        <dt>Basis</dt><dd className="reasons">{o.reasons.map((r, i) => <span key={i} title={`Layer ${r.source_id}${r.res_m ? ` · cell ${r.res_m} m` : ""}`}>{r.layer} {r.value}{r.unit}</span>)}</dd>
      </dl>
      {text && <p className="card-text">{text}</p>}
      {onChoose && <button type="button" className="choose" onClick={onChoose}>SELECT {o.id}</button>}
    </div>
  );
}
