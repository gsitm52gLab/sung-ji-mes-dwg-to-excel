#!/usr/bin/env python3
"""배포용 데이터 스냅샷 갱신 도구.

서버는 배포 환경이든 로컬이든 항상 `frontend/data/` 만 읽는다. HF Space 는
`frontend/` 를 subtree 로 받아가므로 리포지토리 루트의 config.yaml 이나
convert-dxf-to-excel/output/ 은 따라가지 않기 때문이다.

파이프라인을 다시 돌려 대조 결과가 바뀌면 이 스크립트로 스냅샷을 갱신하고
커밋한다. 서버는 이 모듈을 임포트하지 않는다.

    python3 frontend/refresh_data.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"

# 파이프라인이 내는 대조 결과 파일 이름. deckreport / emit_by_zone 와 맞춘다.
COMPARE_CSV = "구역별_대조.csv"


def main() -> int:
    # deckconfig 는 리포지토리 루트의 config.yaml 을 읽는다. 개발 환경에서만
    # 쓰이므로 sys.path 조작을 서버가 아닌 이 도구 안에 가둔다.
    sys.path.insert(0, str(HERE.parent / "convert-dxf-to-excel"))
    try:
        from deckconfig import cfg
    except Exception as exc:
        print(f"config.yaml 을 읽지 못했습니다: {exc}", file=sys.stderr)
        return 1

    src = Path(cfg.by_zone_dir) / COMPARE_CSV
    if not src.exists():
        print(
            f"대조 결과가 없습니다: {src}\n"
            "먼저 파이프라인을 돌려 구역별 대조 결과를 만들어 주세요.",
            file=sys.stderr,
        )
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dst = DATA_DIR / COMPARE_CSV
    shutil.copy2(src, dst)
    print(f"스냅샷 갱신: {dst}  ({dst.stat().st_size:,} bytes)")
    print("변경 내용을 커밋해야 배포에 반영됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
