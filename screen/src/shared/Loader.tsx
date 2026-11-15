// 기다리는 중 표시 — 점 아홉 개(3×3)의 둘레를 빛이 한 바퀴씩 돈다.
//
// 그림일 뿐이다. 무엇을 기다리는지는 부르는 쪽이 글(label)로 준다. 얼마나 걸릴지는 알 수 없으므로 진행률이나 남은 시간을 그리지 않는다.
// 모양은 shared/style.css의 .loader에 있다.

// 칸마다 불이 켜지는 차례(가운데 칸은 켜지지 않는다): 왼쪽 위에서 시작해 시계 방향으로 돈다
const ORDER: (number | null)[] = [0, 1, 2, 7, null, 3, 6, 5, 4];
const STEP_MS = 108;

export function Loader({ label, className = "" }: { label?: string; className?: string }) {
  return (
    <span role="status" className={`loader${className ? ` ${className}` : ""}`}>
      <span className="loader-grid" aria-hidden="true">
        {ORDER.map((n, i) => <i key={i} className={n === null ? "hole" : ""} style={n === null ? undefined : { animationDelay: `${n * STEP_MS}ms` }} />)}
      </span>
      {label && <span className="loader-label">{label}</span>}
    </span>
  );
}
