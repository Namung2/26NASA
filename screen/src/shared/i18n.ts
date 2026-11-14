// 화면의 글자. 문장(카드 머리줄, 알림, 되읽기)은 프로그램이 만들어 스냅샷에 실어 보내고, 여기에는 칸의 이름표만 둔다.
// 금지어(R-52): 추천·권장·최적 같은 말을 여기에 두지 않는다.
export const LABEL: Record<string, string> = {
  continue_plan: "계획 유지", hyp_target: "가설 목표", restore_plan: "이전 계획으로", drop_last: "마지막 지점 빼기", stay: "머물기", return_rover: "로버로 귀환",
};
export const KIND: Record<string, string> = { route: "이동", stay: "머묾", return: "귀환" };
export const GRADE: Record<string, string> = { LOW: "낮음", MED: "보통", HIGH: "높음" };
export const RULE: Record<string, string> = { strata_continuity: "층서 연속", proximity: "근접 군집", unit_boundary: "단위 경계", erosion_exposure: "침식 노출" };
export const DIRECTION = ["북", "북동", "동", "남동", "남", "남서", "서", "북서"];
export const CONFIDENCE = ["가능성 낮음", "반반", "가능성 높음"];
export const CONFIDENCE_RANGE = ["0~33 %", "33~66 %", "66~100 %"];
export const BINDING: Record<string, string> = { sunset: "일몰", eva_max: "EVA 최대 시간" };
export const CAUSE_MARK: Record<string, string> = { route: "경로 갈림길", obs: "관측으로 지도가 바뀜", hyp: "가설로 지도가 바뀜", other: "상황 변화" };
export const SORT: Record<string, string> = {
  unsorted: "정렬 안 함", time_min: "시간", max_slope_deg: "최대 경사", dose_uSv: "선량", value: "과학 가치", info_gain: "정보 이득", nlt_margin_min: "출발 한계 여유",
};
export const LAYER: Record<string, string> = {
  hillshade: "음영 기복", slope: "경사", units: "지질 단위", minerals: "광물", prior: "바탕 지도(과학 가치)", link: "링크 안 되는 곳", shadow: "그림자(지금 시간대)",
};
export const OVER: Record<string, string> = { max_slope_deg: "경사 한계 초과", dose_uSv: "선량 경고 초과" };
export const MINERAL: Record<string, string> = {
  olivine: "감람석", mg_carbonate: "Mg 탄산염", fe_mg_smectite: "Fe/Mg 스멕타이트", olivine_smectite: "감람석+스멕타이트", olv_smect_2p2: "감람석+스멕타이트(2.2 µm)",
  carb_2p2: "탄산염(2.2 µm)", hcp: "고칼슘 휘석", lcp: "저칼슘 휘석", kaolinite: "카올리나이트", mg_smectite_2: "Mg 스멕타이트",
};

export function clock(t: number): string {
  const s = Math.max(0, Math.floor(t));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

// 걷는 시간의 표기: "약 N분 M초". 시간은 어림값이라 늘 '약'을 붙인다. 프로그램이 준 값(분)을 분·초로 나눠 적을 뿐 다시 계산하지 않는다
export function approx(min: number): string {
  const total = Math.round(min * 60);
  const m = Math.floor(total / 60), s = total % 60;
  return s ? `약 ${m}분 ${s}초` : `약 ${m}분`;
}
