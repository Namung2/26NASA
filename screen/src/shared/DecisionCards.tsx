// 결정 지점: 머리줄 + 정렬 고르기 + 옵션 카드 2~3장 (S3c §6.2).
//
// - 머리줄만 "왜 떴는가"에 따라 달라진다(문장은 프로그램이 만든 dp_text[0], 표식은 cause_kind). 카드는 건드리지 않는다.
// - 처음에 골라져 있거나 포커스된 카드가 없다. Enter만으로는 아무것도 골라지지 않는다 — 카드의 단추를 직접 눌러야 한다.
// - 카드에 마우스를 올리면(터치면 카드를 누르면) 그 카드의 경로만 지도에 미리 보인다(onPreview). 미리 보기는 화면 안의 일이다 —
//   프로그램에 보내지 않고, 고른 것으로 치지 않는다. 처음에는 어느 카드도 미리 보이지 않는다.
// - 마우스가 올라간 카드는 마우스 쪽으로 살짝 기운다(tilt). 어느 카드든 똑같이 움직이고, 마우스를 떼면 제자리로 온다.
//   크기·색·칸 순서는 올려도 그대로다. 기울기는 감싼 칸(card-slot)이 하고, 카드 컴포넌트에는 손대지 않는다.
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

// 마우스가 카드의 어디에 있는지를 칸의 CSS 변수로 넘긴다(기울기). 모양은 style.css의 .card-slot에 있다
const TILT_DEG = 3.5;
function tilt(e: React.PointerEvent<HTMLDivElement>) {
  if (e.pointerType !== "mouse") return;
  const el = e.currentTarget, r = el.getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
  el.style.setProperty("--ry", `${((x - 0.5) * 2 * TILT_DEG).toFixed(2)}deg`);
  el.style.setProperty("--rx", `${((0.5 - y) * 2 * TILT_DEG).toFixed(2)}deg`);
}
function untilt(e: React.PointerEvent<HTMLDivElement>) {
  for (const k of ["--rx", "--ry"]) e.currentTarget.style.removeProperty(k);
}

export function sortOptions(options: Option[], key: SortKey): Option[] {
  if (key === "unsorted") return options;
  const sign = ASC.includes(key) ? 1 : -1;
  return [...options].sort((a, b) => sign * (pick(a, key) - pick(b, key)));
}

export function DecisionCards({ dp, text, source, ageS, meta, onChoose, onPreview }: {
  dp: DecisionPoint; text: string[]; source: string; ageS: number; meta: Meta | null; onChoose: (optionId: string, sortKey: SortKey) => void;
  onPreview?: (optionId: string | null) => void;
}) {
  const [sort, setSort] = useState<SortKey>("unsorted");
  const sentence = (o: Option) => text[1 + dp.options.findIndex((x) => x.id === o.id)];
  return (
    <section className={`dp${dp.forced ? " forced" : ""}`}>
      <header className="dp-head">
        <span className={`cause cause-${dp.cause_kind}`}>{dp.forced ? "Safety" : CAUSE_MARK[dp.cause_kind]}</span>
        <strong>{text[0] ?? ""}</strong>
        {/* 카드는 계산한 순간의 위치·시각 기준이다. 떠 있는 동안 걸어도 다시 계산되지 않으므로, 얼마나 지난 카드인지 늘 적어 둔다 */}
        {source === "cache" && <span className="cache">Cards received before the link dropped · computed {Math.round(ageS)} s ago</span>}
        {source === "local" && <span className="cache">Computed on the device · {Math.round(ageS)} s ago</span>}
        {source === "rover" && <span className="age">Computed {Math.round(ageS)} s ago</span>}
        <label className="sort">Sort
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
            {Object.entries(SORT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </header>
      {dp.notices.length > 0 && <p className="dp-notice">{text.slice(1 + dp.options.length).join(" ")}</p>}
      <div className="cards">
        {sortOptions(dp.options, sort).map((o) => (
          // 카드를 감싼 칸: 올림·누름·포커스를 받아 미리 보기만 알린다. 카드 컴포넌트에는 손대지 않는다
          <div key={o.id} className="card-slot"
            onPointerEnter={() => onPreview?.(o.id)}
            onPointerMove={tilt}
            onPointerLeave={(e) => { untilt(e); if (e.pointerType === "mouse") onPreview?.(null); }}
            onFocus={() => onPreview?.(o.id)} onBlur={() => onPreview?.(null)}>
            <OptionCard o={o} meta={meta} text={sentence(o)} onChoose={() => onChoose(o.id, sort)} />
          </div>
        ))}
      </div>
    </section>
  );
}
