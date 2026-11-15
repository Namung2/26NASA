"""시나리오를 화면 없이 끝까지 돌리고 expect를 판정한다 (docs/spec/S5 §5).

    .venv/bin/python -m sim.runner sim/scenarios/V1_apollo17_station4.yaml
    .venv/bin/python -m sim.runner sim/scenarios/*.yaml --bundle data/bundles/jezero_west_v1 --out reports

하는 일: 시나리오 읽기 → 시뮬레이터로 완주 → (rerun_identical이 있으면 한 번 더) → expect/timing 판정 → reports/<시나리오>.md, .json, .jsonl.
돌려주는 값(Report.passed)은 tests/test_v6_scenario.py가 그대로 단언한다. 실패가 하나라도 있으면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from .expect import REGISTRY, CheckResult, Ctx, timing
from .scenario import load_scenario
from .sim import Sim


@dataclass(frozen=True)
class Report:
    scenario: str
    passed: bool
    checks: list[CheckResult]
    timings: list[CheckResult]
    log_digest: str
    bundle_id: str
    params_digest: str
    home: bool                 # 로버에 돌아왔는가
    eva_end_min: float         # 끝난 시각 (EVA 경과 분)
    n_dp: int                  # 화면에 뜬 결정 지점 수
    wall_s: float              # 한 번 도는 데 걸린 실제 시간


def _params_digest(paths: tuple[str, ...]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(Path(p).read_bytes())
    return h.hexdigest()[:16]


def run_scenario(path: str | Path, *, bundle_root: str = "data/bundles/jezero_west_v1", params_path: str = "config/params.yaml",
                 keep_log: list | None = None, any_site: bool = False) -> Report:
    sc = load_scenario(path)
    if sc.scenario != Path(path).stem:
        raise ValueError(f"시나리오 이름({sc.scenario})이 파일 이름({Path(path).stem})과 다르다")
    t0 = time.time()
    sim = Sim(sc, bundle_root, params_path=params_path, any_site=any_site)
    log = sim.run()
    wall = time.time() - t0
    rerun = None
    if any("rerun_identical" in e for e in sc.expect):
        rerun = Sim(sc, bundle_root, params_path=params_path, any_site=any_site).run().digest()
    ctx = Ctx(log=log, scenario=sc, bundle_root=bundle_root, params=yaml.safe_load(Path(params_path).read_text()), rerun_digest=rerun)
    checks: list[CheckResult] = []
    for item in sc.expect:
        for name, arg in item.items():
            fn = REGISTRY.get(name)
            checks.append(fn(ctx, arg) if fn else CheckResult(name, False, "모르는 판정 이름"))
    timings = [timing(ctx, item) for item in sc.timing]
    if keep_log is not None:
        keep_log.append(log)
    # D 시나리오는 완주가 통과 기준이고, timing은 리포트로만 낸다 (S5 §5)
    passed = all(c.ok for c in checks) and (sc.kind == "V" or sim.home or sc.until_min is not None)
    return Report(scenario=sc.scenario, passed=passed, checks=checks, timings=timings, log_digest=log.digest(), bundle_id=sim.meta["bundle_id"],
                  params_digest=_params_digest((params_path, "config/tiers.yaml")), home=sim.home, eva_end_min=round(sim.t / 60.0, 1),
                  n_dp=len(log.of("dp")), wall_s=round(wall, 1))


def write_report(r: Report, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{r.scenario}.json").write_text(json.dumps(asdict(r), ensure_ascii=False, indent=1))
    mark = lambda ok: "통과" if ok else "실패"
    lines = [f"# {r.scenario} — {mark(r.passed)}", "",
             f"- 번들 `{r.bundle_id}`, 설정 다이제스트 `{r.params_digest}`, 기록 다이제스트 `{r.log_digest[:16]}`",
             f"- 끝난 시각 EVA {r.eva_end_min:.1f}분, 로버 도착 {'예' if r.home else '아니오'}, 결정 지점 {r.n_dp}개, 실행 {r.wall_s}초", ""]
    if r.checks:
        lines += ["| 판정 | 결과 | 내용 |", "|---|---|---|"] + [f"| `{c.name}` | {mark(c.ok)} | {c.detail} |" for c in r.checks] + [""]
    if r.timings:
        lines += ["| 단계 | 결과 | 걸린 시간 |", "|---|---|---|"] + [f"| {c.name} | {mark(c.ok)} | {c.detail} |" for c in r.timings] + [""]
    md = out / f"{r.scenario}.md"
    md.write_text("\n".join(lines))
    return md


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="시나리오를 화면 없이 돌리고 판정한다")
    ap.add_argument("scenarios", nargs="+")
    ap.add_argument("--bundle", default="data/bundles/jezero_west_v1")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--any-site", action="store_true", help="시나리오에 적힌 구역이 아닌 번들로도 돌린다(다른 구역 시험용)")
    a = ap.parse_args(argv)
    ok = True
    for path in a.scenarios:
        logs: list = []
        r = run_scenario(path, bundle_root=a.bundle, keep_log=logs, any_site=a.any_site)
        md = write_report(r, a.out)
        logs[0].to_jsonl(Path(a.out) / f"{r.scenario}.jsonl")
        print(f"{'통과' if r.passed else '실패'}  {r.scenario}  (EVA {r.eva_end_min:.0f}분에 끝, 결정 지점 {r.n_dp}개, {r.wall_s}초) → {md}")
        for c in r.checks + r.timings:
            print(f"   {'✓' if c.ok else '✗'} {c.name}: {c.detail}")
        ok = ok and r.passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
