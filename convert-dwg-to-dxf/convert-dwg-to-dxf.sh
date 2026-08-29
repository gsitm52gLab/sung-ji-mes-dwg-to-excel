#!/usr/bin/env bash
# dwg -> dxf 변환. 입출력 경로는 루트 config.yaml 단일 진실 공급원에서 읽는다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 루트 config.yaml 값을 절대경로 환경변수로 로드 (DWG_DIR, DXF_DIR 등)
eval "$(python3 "$SCRIPT_DIR/../convert-dxf-to-excel/deckconfig.py" --export)"

mkdir -p "$DXF_DIR"

docker run --rm --platform linux/amd64 \
  -v "$DWG_DIR:/input" \
  -v "$DXF_DIR:/output" \
  oda-converter \
  bash -c "xvfb-run -a ODAFileConverter /input /output ACAD2018 DXF 0 1 > /output/log.txt 2>&1; echo EXIT_CODE:\$?"
