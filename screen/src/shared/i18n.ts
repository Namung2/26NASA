// 화면의 글자. 문장(카드 머리줄, 알림, 되읽기)은 프로그램이 만들어 스냅샷에 실어 보내고, 여기에는 칸의 이름표만 둔다.
// 금지어(R-52): 추천·권장·최적 같은 말을 여기에 두지 않는다.
export const LABEL: Record<string, string> = {
  continue_plan: "Keep plan", hyp_target: "Hypothesis target", restore_plan: "Back to earlier plan", drop_last: "Drop last stop", stay: "Stay here", return_rover: "Return to rover",
};
export const KIND: Record<string, string> = { route: "Traverse", stay: "Stay", return: "Return" };
export const GRADE: Record<string, string> = { LOW: "Low", MED: "Medium", HIGH: "High" };
export const RULE: Record<string, string> = { strata_continuity: "Strata continuity", proximity: "Proximity cluster", unit_boundary: "Unit boundary", erosion_exposure: "Erosion exposure" };
export const DIRECTION = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
export const CONFIDENCE = ["Unlikely", "About even", "Likely"];
export const CONFIDENCE_RANGE = ["0–33 %", "33–66 %", "66–100 %"];
export const BINDING: Record<string, string> = { sunset: "Sunset", eva_max: "EVA max time" };
export const CAUSE_MARK: Record<string, string> = { route: "Route fork", obs: "Map changed by observation", hyp: "Map changed by hypothesis", other: "Situation change" };
export const SORT: Record<string, string> = {
  unsorted: "Unsorted", time_min: "Time", max_slope_deg: "Max slope", dose_uSv: "Dose", value: "Science", info_gain: "Info gain", nlt_margin_min: "Margin",
};
export const LAYER: Record<string, string> = {
  hillshade: "Hillshade", slope: "Slope", units: "Geologic units", minerals: "Minerals", prior: "Prior map (science value)", link: "No-link areas", shadow: "Shadow (current time bin)",
};
export const OVER: Record<string, string> = { max_slope_deg: "Over slope limit", dose_uSv: "Over dose warning" };
export const MINERAL: Record<string, string> = {
  olivine: "Olivine", mg_carbonate: "Mg carbonate", fe_mg_smectite: "Fe/Mg smectite", olivine_smectite: "Olivine + smectite", olv_smect_2p2: "Olivine + smectite (2.2 µm)",
  carb_2p2: "Carbonate (2.2 µm)", hcp: "High-Ca pyroxene", lcp: "Low-Ca pyroxene", kaolinite: "Kaolinite", mg_smectite_2: "Mg smectite",
};

export function clock(t: number): string {
  const s = Math.max(0, Math.floor(t));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

// 걷는 시간의 표기: "about N min M s". 시간은 어림값이라 늘 about을 붙인다. 프로그램이 준 값(분)을 분·초로 나눠 적을 뿐 다시 계산하지 않는다
export function approx(min: number): string {
  const total = Math.round(min * 60);
  const m = Math.floor(total / 60), s = total % 60;
  return s ? `about ${m} min ${s} s` : `about ${m} min`;
}
