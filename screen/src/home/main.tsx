// 첫 화면 — 세 걸음으로 고른다: 지도 → 시나리오 → 화면(현장 화면 / 로버 콘솔).
//
// 판단이 없다. 지도와 시나리오의 목록·이름·설명은 프로그램이 준 것(GET /sim/catalog — 번들 메타와 시나리오 파일에 적힌 그대로)이고,
// 여기서는 그것을 늘어놓고, 고른 시나리오를 시작해 달라고 보낼 뿐이다(POST /sim/start).
//
//   1. 지도: 별이 깔린 바탕 위에 지도가 궤도를 돈다. 지도 하나가 궤도의 그림 하나다(그림은 그 지도의 음영 기복 타일).
//      서버에 올라와 있는 지도만 돈다 — 없는 지도를 있는 것처럼 그리지 않는다.
//   2. 시나리오: 고른 지도에서 도는 시나리오의 목록. 지금 돌고 있는 것은 그렇게 적고, 고르면 처음부터 다시 시작하지 않고 이어서 본다.
//   3. 화면: 현장 화면과 로버 콘솔. 구석의 스위치로 보기 방식을 고른다 —
//      Simulation = 화면 아래에 시뮬레이터 조작 막대가 보인다 / Live = 조작 막대를 감춘다(실제 기기에는 그 막대가 없다).
//      이 빌드에서는 기기·로버 프로그램이 시뮬레이터 안에서 돌기 때문에, Live에서도 자료는 시뮬레이터가 만든다. 화면에 그렇게 적는다.
//
// 별 바탕(Galaxy), 등고선 바탕(Topography — 화면을 고르는 걸음), 궤도(OrbitImages)는 React Bits의 것을 그대로 쓴다(src/vendor/, 출처와 라이선스는 그 폴더의 README). 목록과 스위치는 여기서 새로 썼다.
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { clock } from "../shared/i18n";
import { Loader } from "../shared/Loader";
import { getMode, setMode, type Mode } from "../shared/mode";
import "../shared/style.css";
import Galaxy from "../vendor/Galaxy.jsx";
import OrbitImages from "../vendor/OrbitImages.jsx";
import Topography from "../vendor/Topography.jsx";

interface ScenarioInfo { id: string; kind: "D" | "V"; title: string; summary: string; start_min: number; stops: string[] }
interface MapInfo { id: string; site: string; extent_m: [number, number]; pois: number; loaded: boolean; thumb: string | null; scenarios: ScenarioInfo[] }
interface Running { bundle: string; scenario: string; running: boolean; t: number; home: boolean; speed: number }
interface Catalog { maps: MapInfo[]; running: Running }
type Step = "map" | "scenario" | "screen";

const KIND: Record<string, string> = { D: "DEMO", V: "VALIDATION" };
const siteName = (s: string) => s.replace(/_/g, " ").toUpperCase();
const km = (m: number) => `${m / 1000} km`;

// 두 가지 가운데 하나를 고르는 스위치
function ModeSwitch({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const live = mode === "live";
  return (
    <div className="modeswitch">
      <span className={live ? "" : "on"}>SIMULATION</span>
      <button type="button" role="switch" aria-checked={live} aria-label="Live mode" className={live ? "on" : ""} onClick={() => onChange(live ? "sim" : "live")}><i /></button>
      <span className={live ? "on" : ""}>LIVE</span>
    </div>
  );
}

function Home() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [failed, setFailed] = useState(false);
  const [step, setStep] = useState<Step>("map");
  const [mapId, setMapId] = useState<string | null>(null);
  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setModeState] = useState<Mode>(getMode);

  const load = () => fetch("/sim/catalog").then((r) => (r.ok ? r.json() : Promise.reject())).then((c: Catalog) => { setCat(c); setFailed(false); }).catch(() => setFailed(true));
  useEffect(() => { void load(); const id = window.setInterval(load, 2000); return () => window.clearInterval(id); }, []);

  const map = cat?.maps.find((m) => m.id === mapId) ?? null;
  const scenario = map?.scenarios.find((s) => s.id === scenarioId) ?? null;
  const isRunning = (id: string) => !!cat && cat.running.scenario === id && cat.running.running && cat.running.bundle === mapId;   // 같은 시나리오라도 다른 지도에서 돌고 있으면 새로 시작한다
  const start = async (id: string) => {
    setBusy(true);
    try { await fetch("/sim/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: id, speed: 10, manual: true, bundle: mapId }) }); await load(); }
    finally { setBusy(false); }
  };
  const pickScenario = async (id: string) => {
    if (!isRunning(id)) await start(id);            // 이미 돌고 있는 것을 고르면 다시 시작하지 않고 이어서 본다
    setScenarioId(id); setStep("screen");
  };
  const changeMode = (m: Mode) => { setMode(m); setModeState(m); };

  const orbiting = cat?.maps.filter((m) => m.loaded && m.thumb) ?? [];
  return (
    <div className="home">
      {/* 바탕: 지도와 시나리오를 고르는 동안은 별, 화면을 고르는 걸음에서는 등고선 */}
      {step === "screen"
        ? <div className="home-back" aria-hidden="true"><Topography color="#e8a25c" lineCount={24} tilt={36} speed={0.16} glow={0.45} fog={0.55} brightness={0.8} clickEffect="none" /></div>
        : <div className="galaxy" aria-hidden="true"><Galaxy density={1.1} glowIntensity={0.28} saturation={0} twinkleIntensity={0.35} rotationSpeed={0.04} speed={0.6} mouseInteraction={false} clickWarp={false} transparent /></div>}
      <header className="home-top">
        <b>BINGOTIME</b>
        <ol className="home-steps">
          <li className={step === "map" ? "on" : ""}><button type="button" onClick={() => setStep("map")}>1 · MAP{map ? ` — ${siteName(map.site)}` : ""}</button></li>
          <li className={step === "scenario" ? "on" : ""}><button type="button" disabled={!map} onClick={() => setStep("scenario")}>2 · SCENARIO{scenario ? ` — ${scenario.id}` : ""}</button></li>
          <li className={step === "screen" ? "on" : ""}><button type="button" disabled={!scenario} onClick={() => setStep("screen")}>3 · SCREEN</button></li>
        </ol>
        {step === "screen" && <ModeSwitch mode={mode} onChange={changeMode} />}
      </header>

      {!cat && <div className="home-mid">{failed ? <p className="none">The program did not answer. Start it with: python -m sim.live</p> : <Loader label="Reading maps and scenarios" />}</div>}

      {cat && step === "map" && (
        <main className="home-mid">
          <div className="home-orbit">
            <OrbitImages images={orbiting.map((m) => ({ src: m.thumb, alt: `Map ${siteName(m.site)}` }))} shape="ellipse" baseWidth={1000} radiusX={380} radiusY={120} rotation={-8}
              duration={48} itemSize={132} itemRadius={66} showPath pathColor="rgba(239,232,220,0.22)" pathWidth={1} hoverScale={1.1} shadow={0.5}
              onItemClick={(i: number) => { setMapId(orbiting[i].id); setStep("scenario"); }}
              centerContent={<div className="home-center"><h1>Choose a map</h1><p>Each body in orbit is one map loaded on this program.</p></div>} />
          </div>
          <ul className="home-maps">
            {cat.maps.map((m) => (
              <li key={m.id}>
                <button type="button" disabled={!m.loaded} onClick={() => { setMapId(m.id); setStep("scenario"); }}>
                  <b>{siteName(m.site)}</b>
                  <span>{m.id} · {km(m.extent_m[0])} × {km(m.extent_m[1])} · {m.pois} sites · {m.scenarios.length} scenarios{m.loaded ? "" : " · not loaded on this program"}</span>
                </button>
              </li>
            ))}
          </ul>
        </main>
      )}

      {cat && step === "scenario" && map && (
        <main className="home-mid">
          <div className="home-head"><h1>{siteName(map.site)}</h1><p>Choose a scenario on this map.</p></div>
          {map.scenarios.length === 0 && <p className="none">No scenario is written for this map.</p>}
          <ul className="home-list">
            {map.scenarios.map((s, i) => (
              <li key={s.id} style={{ animationDelay: `${i * 70}ms` }}>
                <button type="button" disabled={busy} onClick={() => void pickScenario(s.id)}>
                  <span className="hl-kind">{KIND[s.kind] ?? s.kind}</span>
                  <b>{s.title}</b>
                  <span className="hl-sum">{s.summary}</span>
                  <span className="hl-meta">{s.id} · starts at EVA {clock(s.start_min * 60)} · stops {s.stops.join(" → ")}{isRunning(s.id) ? ` · RUNNING NOW — EVA ${clock(cat.running.t)}` : ""}</span>
                </button>
              </li>
            ))}
          </ul>
          {busy && <Loader label="Starting the scenario" />}
        </main>
      )}

      {cat && step === "screen" && map && scenario && (
        <main className="home-mid">
          <div className="home-head"><h1>{scenario.title}</h1><p>{siteName(map.site)} · {isRunning(scenario.id) ? `running — EVA ${clock(cat.running.t)}` : cat.running.scenario === scenario.id ? "ended" : "not running"}</p></div>
          <div className="home-pick">
            <a className="primary" href="/field.html"><b>FIELD SCREEN</b><span>Tablet of the crew member outside</span></a>
            <a href="/console.html"><b>ROVER CONSOLE</b><span>Planning screen for the crew in the rover</span></a>
          </div>
          <p className="home-note">
            {mode === "sim"
              ? "Simulation mode: the screens show the simulator controls (speed, restart, cut link) along the bottom."
              : "Live mode: the simulator controls are hidden, as on a real device. In this build the device and rover programs still run inside the simulator, so the data comes from the scenario above."}
          </p>
          <button type="button" className="home-restart" disabled={busy} onClick={() => void start(scenario.id)}>Restart this scenario from the beginning</button>
        </main>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Home />);
