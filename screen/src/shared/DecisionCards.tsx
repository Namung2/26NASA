// 결정 지점: 머리줄 + 정렬 고르기 + 옵션 카드 2~3장 (S3c §6.2).
//
// - 머리줄만 "왜 떴는가"에 따라 달라진다(문장은 프로그램이 만든 dp_text[0], 표식은 cause_kind). 카드는 건드리지 않는다.
// - 처음에 골라져 있거나 포커스된 카드가 없다. Enter만으로는 아무것도 골라지지 않는다 — 카드의 단추를 직접 눌러야 한다.
// - 정렬은 사람이 고른 한 칸 기준. 고르기 전에는 만들어진 순서 + "정렬 안 함". 정렬은 화면 안의 일이라 프로그램에 보내지 않고,
//   고를 때 그 시점의 정렬 기준만 함께 보낸다(R-53).
import { useState } from "react";
import type { DecisionPoint, Option } from "../types";
import { CAUSE_MARK, SORT } from "./i18n";
import type { Meta } from "./meta";
import { OptionCard } from "./OptionCard";

type SortKey = DecisionPoint["sort_key"];
// 정렬 방향: 작은 값이 먼저인 칸과 큰 값이 먼저인 칸. 이름표나 색으로 "더 낫다"를 뜻하지 않는다 — 늘어놓는 순서일 뿐이다
const ASC: SortKey[] = ["time_min", "max_slope_deg", "dose_uSv"];
const pick = (o: Option, k: SortKey): number => (k === "value" ? o.value_mean : k === "unsorted" ? 0 : (o[k] as number));

export function sortOptions(options: Option[], key: SortKey): Option[] {
  if (key === "unsorted") return options;
  const sign = ASC.includes(key) ? 1 : -1;
  return [...options].sort((a, b) => sign * (pick(a, key) - pick(b, key)));
}

export function DecisionCards({ dp, text, source, ageS, meta, onChoose }: {
  dp: DecisionPoint; text: string[]; source: string; ageS: number; meta: Meta | null; onChoose: (optionId: string, sortKey: SortKey) => void;
}) {
  const [sort, setSort] = useState<SortKey>("unsorted");
  const sentence = (o: Option) => text[1 + dp.options.findIndex((x) => x.id === o.id)];
  return (
    <section className={`dp${dp.forced ? " forced" : ""}`}>
      <header className="dp-head">
        <span className={`cause cause-${dp.cause_kind}`}>{dp.forced ? "안전" : CAUSE_MARK[dp.cause_kind]}</span>
        <strong>{text[0] ?? ""}</strong>
        {source === "cache" && <span className="cache">끊기기 전에 받은 카드 · 계산한 지 {Math.round(ageS)}초</span>}
        {source === "local" && <span className="cache">기기가 직접 계산</span>}
        <label className="sort">정렬
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            {Object.entries(SORT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </header>
      {dp.notices.length > 0 && <p className="dp-notice">{text.slice(1 + dp.options.length).join(" ")}</p>}
      <div className="cards">
        {sortOptions(dp.options, sort).map((o) => <OptionCard key={o.id} o={o} meta={meta} text={sentence(o)} onChoose={() => onChoose(o.id, sort)} />)}
      </div>
    </section>
  );
}
