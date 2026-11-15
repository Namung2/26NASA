// 첫 화면 — 현장 화면과 로버 콘솔 가운데 어디로 갈지 고른다. 판단도 데이터도 없다.
//
// 배경의 등고선 그림은 src/vendor/Topography.jsx 가 그린다. 그 파일은 밖에서 가져온 것이라 저장소에 올리지 않는다(.gitignore).
// 그래서 "있으면 쓰고 없으면 그냥 어두운 바탕"으로 읽는다 — 파일이 없는 자리에서도 빌드가 된다.
import { type ComponentType, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "../shared/style.css";

type Backdrop = ComponentType<Record<string, unknown>>;
const found = import.meta.glob<{ default: Backdrop }>("../vendor/Topography.jsx");

function Home() {
  const [Topo, setTopo] = useState<Backdrop | null>(null);
  useEffect(() => {
    const load = Object.values(found)[0];
    if (load) load().then((m) => setTopo(() => m.default)).catch(() => undefined);
  }, []);
  return (
    <div className="home">
      {Topo && <div className="home-back"><Topo color="#e8a25c" lineCount={24} tilt={36} speed={0.16} glow={0.45} fog={0.55} brightness={0.8} clickEffect="none" /></div>}
      <main className="home-box">
        <h1>BINGOTIME</h1>
        <p>On the surface of Mars, a person chooses the next step</p>
        <div className="home-pick">
          <a className="primary" href="/field.html"><b>FIELD SCREEN</b><span>Tablet of the crew member outside</span></a>
          <a href="/console.html"><b>ROVER CONSOLE</b><span>Planning screen for the crew in the rover</span></a>
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<Home />);
