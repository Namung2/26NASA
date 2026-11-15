// 보기 방식: Simulation(시뮬레이터 조작 막대가 보인다) / Live(감춘다 — 실제 기기에는 그 막대가 없다).
// 첫 화면의 스위치로 고르고, 이 브라우저에 적어 둔다. 화면의 겉모습만 바꾼다 — 프로그램에는 보내지 않는다.
export type Mode = "sim" | "live";
const KEY = "bingotime.mode";

export function getMode(): Mode {
  try { return localStorage.getItem(KEY) === "live" ? "live" : "sim"; } catch { return "sim"; }
}

export function setMode(m: Mode): void {
  try { localStorage.setItem(KEY, m); } catch { /* 적어 둘 수 없는 브라우저(사생활 보호 창 등)에서는 이번 화면에서만 적용된다 */ }
}
