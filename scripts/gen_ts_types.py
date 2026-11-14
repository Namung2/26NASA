"""host/wire.py의 모델 → screen/src/types.ts.

    .venv/bin/python scripts/gen_ts_types.py

화면의 타입을 손으로 적지 않는다. 와이어 모델(host/wire.py)이 정본이고, 이 스크립트가 pydantic의 JSON 스키마를 TypeScript로 옮긴다.
wire.py를 고쳤으면 이 스크립트를 다시 돌린다 — 그러면 화면에서 어긋난 곳이 타입 오류(npm run typecheck)로 드러난다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pydantic import TypeAdapter

from host import wire as w

# 화면이 받거나 보내는 최상위 모델. 여기서 닿는 모델은 전부 따라 나온다
TOP = [w.Snapshot, w.ConsoleSnapshot, w.ScreenCmd, w.ConsoleCmd]


def ts_type(s: dict) -> str:
    if "$ref" in s:
        return s["$ref"].split("/")[-1]
    if "const" in s:
        return repr_json(s["const"])
    if "enum" in s:
        return " | ".join(repr_json(v) for v in s["enum"])
    for key in ("anyOf", "oneOf"):
        if key in s:
            return " | ".join(dict.fromkeys(ts_type(x) for x in s[key]))
    t = s.get("type")
    if t == "array":
        if "prefixItems" in s:
            return "[" + ", ".join(ts_type(x) for x in s["prefixItems"]) + "]"
        inner = ts_type(s.get("items", {}))
        return f"({inner})[]" if " | " in inner else f"{inner}[]"
    if t == "object":
        ap = s.get("additionalProperties")
        return f"Record<string, {ts_type(ap)}>" if isinstance(ap, dict) else "Record<string, unknown>"
    return {"string": "string", "integer": "number", "number": "number", "boolean": "boolean", "null": "null"}.get(t, "unknown")


def repr_json(v) -> str:
    import json
    return json.dumps(v, ensure_ascii=False)


def main() -> None:
    defs: dict[str, dict] = {}
    for model in TOP:
        schema = TypeAdapter(model).json_schema(mode="serialization")
        defs.update(schema.pop("$defs", {}))
        defs[model.__name__] = schema
    out = ["// 이 파일은 scripts/gen_ts_types.py가 host/wire.py에서 만든다. 손으로 고치지 않는다.", ""]
    for name in sorted(defs):
        s = defs[name]
        doc = (s.get("description") or "").strip().splitlines()
        if doc:
            out.append(f"/** {doc[0]} */")
        if s.get("type") == "object" and "properties" in s:
            out.append(f"export interface {name} {{")
            for key, prop in s["properties"].items():
                out.append(f"  {key}: {ts_type(prop)};")      # 받는 쪽 기준: 기본값이 있는 필드도 항상 실려 온다
            out.append("}")
        else:
            out.append(f"export type {name} = {ts_type(s)};")
        out.append("")
    path = ROOT / "screen/src/types.ts"
    path.write_text("\n".join(out))
    print(f"{path.relative_to(ROOT)}: 타입 {len(defs)}개")


if __name__ == "__main__":
    main()
