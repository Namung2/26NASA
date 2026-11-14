// 수치·임계의 출처 (R-03). 값 옆의 작은 표식에 올리면 번들 메타에 실린 출처가 뜬다.
// 임시값(TUNE·PLACEHOLDER·TBD)에는 "임시값" 표식이 붙는다.
import { Meta, param } from "./meta";

export function SourceTip({ meta, k }: { meta: Meta | null; k: string }) {
  const p = param(meta, k);
  if (!p) return null;
  const temp = p.status !== "REF" && p.status !== "DESIGN";
  return (
    <span className="src" title={`${p.key} = ${String(p.value)} ${p.unit}\n출처: ${p.source}\n상태: ${p.status}`}>
      ⓘ{temp && <span className="temp">임시값</span>}
    </span>
  );
}
