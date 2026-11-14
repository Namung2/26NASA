// 이 파일은 scripts/gen_ts_types.py가 host/wire.py에서 만든다. 손으로 고치지 않는다.

export interface ChannelView {
  state: "UP" | "DOWN";
  rtt_ms: number;
  loss: number;
  down_for_s: number | null;
}

export interface ChoiceEvent {
  id: string;
  ts: number;
  lts: number;
  node: string;
  geom: GeomPoint | GeomCell | GeomPolyline;
  approved: boolean;
  type: "choice";
  payload: ChoicePayload;
}

export interface ChoicePayload {
  dp_id: string;
  option_id: string;
  options_shown: string[];
  sort_key: string;
  was_hypothesis_option: boolean;
  hyp_ids: string[];
  option_digest: string;
  latency_s: number;
  stops: Stop[];
}

export interface CmdChoose {
  kind: "choose";
  dp_id: string;
  option_id: string;
  sort_key: "unsorted" | "time_min" | "max_slope_deg" | "dose_uSv" | "value" | "info_gain" | "nlt_margin_min";
}

export interface CmdHyp {
  kind: "hyp";
  rule: "strata_continuity" | "proximity" | "unit_boundary" | "erosion_exposure";
  direction_idx: number;
  extent_idx: number;
  confidence_idx: number;
}

export interface CmdHypReply {
  kind: "hyp_reply";
  reply: "approve" | "reject" | "edit";
}

export interface CmdHypWithdraw {
  kind: "hyp_withdraw";
  hyp_id: string;
}

export interface CmdMark {
  kind: "mark";
  what: "poi" | "blocked";
  name: string;
  radius_idx: number;
  note: string;
}

export interface CmdObs {
  kind: "obs";
  found: boolean;
  confirmed: boolean;
  note: string;
}

export interface CmdPhoto {
  kind: "photo";
}

export interface CmdReturn {
  kind: "return";
}

/** 로버 콘솔 → 로버 프로그램. 로버에 탄 사람이 메모를 읽고 가설을 넣는다(R-29). 기준점은 고른 관측(anchor_event)의 위치다. */
export interface ConsoleCmd {
  type: "console_command";
  cmd: CmdHyp | CmdHypReply;
  anchor_event: string | null;
}

/** 로버 프로그램 → 계획 화면(로버 콘솔). */
export interface ConsoleSnapshot {
  t: number;
  lmst: string;
  rover_pos: [number, number] | null;
  candidates: Option[];
  shown_ids: string[];
  hyp_suggestions: HypDraft[];
  crew: CrewStatus;
  alerts: string[];
  recent_decisions: DecisionPoint[];
  recent_events: (HypEvent | ObsEvent | ChoiceEvent | TraceEvent | MarkEvent)[];
  hyps: HypView[];
  obs: ObsMark[];
  traces: TraceMark[];
  missing_layers: string[];
  link_up: boolean;
  shadow_bin: number;
  hyp_draft: HypDraft | null;
}

export interface CrewStatus {
  node: string;
  state: State | null;
  last_rx_s: number;
  nlt: NltView | null;
  plan: Stop[];
  route: [number, number][];
}

export interface DecisionPoint {
  dp_id: string;
  trigger: "fork" | "env" | "link_lost" | "safety" | "user_request";
  cause: string;
  cause_kind: "route" | "obs" | "hyp" | "other";
  ts: number;
  node: string;
  sort_key: "unsorted" | "time_min" | "max_slope_deg" | "dose_uSv" | "value" | "info_gain" | "nlt_margin_min";
  options: Option[];
  notices: string[];
  forced: boolean;
  inputs_digest: string;
}

export interface GaugeView {
  bearing_deg: number;
  distance_m: number;
  time_min: number;
}

export interface GeomCell {
  kind: "cell";
  res_m: number;
  cell: [number, number];
}

export interface GeomPoint {
  kind: "point";
  xy: [number, number];
}

export interface GeomPolyline {
  kind: "polyline";
  xy: [number, number][];
}

/** 확인 창에 뜨는, 메뉴에서 고르는 중인 가설. 빈칸이 남아 있으면 승인할 수 없다 — 시스템은 빈칸을 채우지 않는다. */
export interface HypDraft {
  rule: "strata_continuity" | "proximity" | "unit_boundary" | "erosion_exposure" | null;
  direction_idx: number | null;
  extent_idx: number | null;
  confidence_idx: number | null;
  missing: string[];
  readback: string;
  withdraw_hyp_id: string | null;
}

export interface HypEvent {
  id: string;
  ts: number;
  lts: number;
  node: string;
  geom: GeomPoint | GeomCell | GeomPolyline;
  approved: boolean;
  type: "hyp";
  payload: HypPayload;
}

export interface HypPayload {
  hyp_id: string;
  rule: "strata_continuity" | "proximity" | "unit_boundary" | "erosion_exposure";
  direction_deg: number;
  extent_m: number;
  confidence: number;
  origin: "menu" | "script" | "suggested";
  anchor_event: string | null;
  supersedes: string | null;
}

export interface HypView {
  hyp_id: string;
  rule: "strata_continuity" | "proximity" | "unit_boundary" | "erosion_exposure";
  xy: [number, number];
  direction_deg: number;
  extent_m: number;
  conf_chosen: number;
  conf_now: number;
  n_used: number;
  conf_chosen_name: string;
  conf_now_name: string;
}

export interface MarkEvent {
  id: string;
  ts: number;
  lts: number;
  node: string;
  geom: GeomPoint | GeomCell | GeomPolyline;
  approved: boolean;
  type: "mark";
  payload: MarkPayload;
}

export interface MarkPayload {
  what: "poi" | "blocked";
  name: string;
  radius_m: number;
  photo: string | null;
  note: string;
}

export interface NltView {
  t_depart: number;
  slack_min: number;
  binding: "sunset" | "eva_max";
  degraded: boolean;
  return_dist_m: number;
  return_time_min: number;
}

export interface ObsEvent {
  id: string;
  ts: number;
  lts: number;
  node: string;
  geom: GeomPoint | GeomCell | GeomPolyline;
  approved: boolean;
  type: "obs";
  payload: ObsPayload;
}

/** 지도에 찍는 관측 한 점(자유 메모 포함). */
export interface ObsMark {
  id: string;
  xy: [number, number];
  found: boolean;
  confirmed: boolean;
  note: string;
  node: string;
  ts: number;
}

export interface ObsPayload {
  obs_id: string;
  kind: "found" | "not_found";
  signal: string;
  confirmed: boolean;
  note: string;
}

export interface Option {
  id: string;
  kind: "route" | "stay" | "return";
  label_key: string;
  path: [number, number][];
  stops: Stop[];
  time_min: number;
  max_slope_deg: number;
  dose_uSv: number;
  value_mean: number;
  value_var: number;
  info_gain: number;
  explore_count: number;
  comm_loss_min: number;
  from_hypothesis: boolean;
  reasons: Reason[];
  value_lo: number;
  value_hi: number;
  value_grade: "LOW" | "MED" | "HIGH";
  hyp_ids: string[];
  prior_only: boolean;
  nlt_margin_min: number;
  late: boolean;
  over_limit: string[];
  nlt_binding: "sunset" | "eva_max";
  return_time_min: number;
  profile: [number, number][];
  digest: string;
}

export interface Reason {
  layer: string;
  cell: [number, number] | null;
  res_m: number | null;
  value: number;
  unit: string;
  source_id: string;
}

/** 화면 → 프로그램. 화면은 응답을 기다리지 않는다 — 결과는 다음 스냅샷에 나타난다. */
export interface ScreenCmd {
  type: "command";
  cmd: CmdChoose | CmdObs | CmdHyp | CmdHypReply | CmdHypWithdraw | CmdReturn | CmdPhoto | CmdMark;
}

/** 기기 프로그램 → 현장 화면. 틱마다 전체를 보낸다. 화면이 계산해 채우는 필드는 없다. */
export interface Snapshot {
  state: State;
  lmst: string;
  sigma_m: number;
  pos_warn: boolean;
  traces: TraceMark[];
  obs: ObsMark[];
  channels: Record<string, ChannelView>;
  plan: Stop[];
  route: [number, number][];
  return_rover: [number, number][];
  visited: Stop[];
  track: [number, number][];
  nlt: NltView | null;
  nlt_warn: boolean;
  gauge: GaugeView | null;
  dp: DecisionPoint | null;
  dp_source: "rover" | "local" | "cache";
  dp_age_s: number;
  options_paused: boolean;
  pending_events: number;
  dp_text: string[];
  hyp_draft: HypDraft | null;
  hyps: HypView[];
  log_count: number;
  log_persisted: boolean;
  missing_layers: string[];
  notices: string[];
  tau_warn: boolean;
  shadow_bin: number;
}

export interface State {
  t: number;
  node: string;
  pos: [number, number];
  sigma: number;
  tau_dust: number;
  dose_rate: number;
  spe: boolean;
  sun_elev: number;
  heading_deg: number;
  dose_cum_uSv: number;
  sun_az: number;
  t_air_c: number | null;
  link_mode: "FULL" | "LOCAL";
  rover_pos: [number, number] | null;
}

export interface Stop {
  xy: [number, number];
  poi_id: string | null;
  dwell_min: number;
  purpose: "poi" | "hyp_target" | "landmark" | "rover";
}

export interface TraceEvent {
  id: string;
  ts: number;
  lts: number;
  node: string;
  geom: GeomPoint | GeomCell | GeomPolyline;
  approved: boolean;
  type: "trace";
  payload: TracePayload;
}

export interface TraceMark {
  xy: [number, number];
  kind: "photo" | "mention";
  fade: number;
  kept: boolean;
}

export interface TracePayload {
  kind: "photo" | "mention";
}
