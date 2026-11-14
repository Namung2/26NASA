// 시뮬레이터 조작 막대 — 보여 주기·개발 전용이다(S5 §6). 실제 기기의 화면에는 없다.
// 서버(/sim/*)가 없으면 아무것도 그리지 않는다.
import { useEffect, useState } from "react";
import { clock } from "./i18n";

interface SimState { scenario: string; speed: number; manual: boolean; running: boolean; t: number; home: boolean; link: Record<string, string | null>; scenarios: string[] }

async function post(path: string, body: unknown): Promise<void> {
  await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export function SimBar() {
  const [s, setS] = useState<SimState | null>(null);
  const [name, setName] = useState("");
  const [manual, setManual] = useState(true);
  useEffect(() => {
    const load = () => fetch("/sim/state").then((r) => (r.ok ? r.json() : null)).then((j) => setS(j as SimState | null)).catch(() => setS(null));
    load();
    const id = window.setInterval(load, 1000);
    return () => window.clearInterval(id);
  }, []);
  if (!s) return null;
  const lost = s.link.uhf === "LOST";
  return (
    <div className="simbar">
      <b>시뮬레이터 조작</b><small>(보여 주기용 — 실제 기기에는 없음)</small>
      <select value={name || s.scenario} onChange={(e) => setName(e.target.value)}>{s.scenarios.map((x) => <option key={x}>{x}</option>)}</select>
      <label><input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} /> 가설·선택은 사람이</label>
      <button type="button" onClick={() => post("/sim/start", { scenario: name || s.scenario, speed: s.speed || 10, manual })}>처음부터</button>
      <span className="sep" />
      배속 {[0, 1, 10, 30, 120].map((v) => <button type="button" key={v} className={s.speed === v ? "on" : ""} onClick={() => post("/sim/speed", { speed: v })}>{v === 0 ? "멈춤" : `${v}×`}</button>)}
      <span className="sep" />
      <button type="button" className={lost ? "on" : ""} onClick={() => post("/sim/link", { ch: "both", state: lost ? "AUTO" : "LOST" })}>{lost ? "링크 되살리기" : "링크 끊기"}</button>
      <span className="sep" />
      <span>{s.scenario} · EVA {clock(s.t)}{s.home ? " · 로버 도착" : ""}{!s.running ? " · 끝" : ""}</span>
    </div>
  );
}
