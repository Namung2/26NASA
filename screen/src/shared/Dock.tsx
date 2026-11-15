// 조작 단추 묶음(독) — 지도 오른쪽에 떠 있는 세로 단추 줄.
//
// 판단이 없다. 받은 단추를 받은 순서대로 그리고, 누르면 그 단추의 onClick을 부를 뿐이다.
// - 이름은 늘 단추 안에 적혀 있다(올려야만 보이는 이름표로 숨기지 않는다 — 장갑 낀 손은 올릴 수 없다).
// - 마우스가 가까이 오면 그 둘레의 단추가 조금 커진다. 자리는 그대로다(왼쪽으로만 커진다).
// - 지도 칸이 낮으면 줄 전체가 그 높이에 맞게 줄어든다. 줄일 수 있는 데까지 줄여도 안 들어가면 두 줄로 선다.
// 모양은 shared/style.css의 .dock에 있다.
import { type ReactNode, useLayoutEffect, useRef } from "react";

export type DockItem =
  | { sep: true }
  | { sep?: false; key: string; icon: ReactNode; label: string; title?: string; on?: boolean; tone?: "warm"; onClick: () => void };

const REACH_PX = 120;     // 마우스에서 이만큼 안에 있는 단추가 커진다
const GROW = 0.22;        // 가장 가까운 단추가 커지는 정도
const MIN_FIT = 0.6;      // 줄어드는 한계(이보다 작으면 누르기 어렵다)

export function Dock({ items, label }: { items: DockItem[]; label: string }) {
  const root = useRef<HTMLDivElement>(null);

  // 지도 칸의 높이에 맞춘다
  useLayoutEffect(() => {
    const el = root.current, host = el?.parentElement;
    if (!el || !host) return undefined;
    const fit = () => {
      // 다 들어가려면 필요한 높이를 단추 수로 셈한다(타일 58, 사이 6, 구분선 1, 안쪽 여백 14 — style.css의 .dock과 같은 값).
      // 줄일 수 있는 데까지 줄여도 안 들어가면 CSS가 둘째 줄(왼쪽)로 넘긴다 — 단추가 지도 칸 밖으로 잘려 나가지 않게
      const tiles = el.querySelectorAll(".dock-item").length, seps = el.querySelectorAll(".dock-sep").length;
      const need = tiles * 58 + seps + (tiles + seps - 1) * 6 + 14, room = host.clientHeight - 16;
      el.style.setProperty("--fit", String(Math.min(1, Math.max(MIN_FIT, room / need))));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(host);
    return () => ro.disconnect();
  }, [items.length]);

  const swell = (y: number | null) => {
    root.current?.querySelectorAll<HTMLElement>(".dock-item").forEach((b) => {
      if (y === null) return b.style.removeProperty("--s");
      const r = b.getBoundingClientRect(), d = Math.min(Math.abs(y - (r.top + r.height / 2)) / REACH_PX, 1);
      b.style.setProperty("--s", (1 + GROW * Math.cos((d * Math.PI) / 2)).toFixed(3));
    });
  };

  return (
    <div ref={root} className="dock" role="toolbar" aria-label={label} aria-orientation="vertical"
      onPointerMove={(e) => { if (e.pointerType === "mouse") swell(e.clientY); }} onPointerLeave={() => swell(null)}>
      {items.map((it, i) => it.sep
        ? <span key={`sep${i}`} className="dock-sep" />
        : (
          <button key={it.key} type="button" className={`dock-item${it.on ? " on" : ""}${it.tone ? ` ${it.tone}` : ""}`}
            title={it.title} aria-label={it.title ?? it.label} aria-pressed={it.on} onClick={it.onClick}>
            <span className="dock-face">{it.icon}<span>{it.label}</span></span>
          </button>
        ))}
    </div>
  );
}
