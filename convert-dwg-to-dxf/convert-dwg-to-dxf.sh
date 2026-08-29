#!/usr/bin/env bash
# DWG → DXF 변환. 경로/파라미터는 config.yaml 에서 읽는다.
set -euo pipefail

# 스크립트 위치 기준으로 경로를 해석한다 (cwd 에 흔들리지 않게).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$DIR/config.yaml"

cfg() { python3 "$DIR/read_config.py" "$CONFIG" "$1"; }

IMAGE="$(cfg docker.image)"
PLATFORM="$(cfg docker.platform)"
INPUT_DIR="$(cfg input.dir)"
OUTPUT_DIR="$(cfg output.dir)"
OUT_VERSION="$(cfg oda.output_version)"
OUT_TYPE="$(cfg oda.output_type)"
RECURSE="$(cfg oda.recurse)"
AUDIT="$(cfg oda.audit)"

# 상대경로는 스크립트 위치 기준 절대경로로 변환한다.
INPUT_ABS="$(cd "$DIR/$INPUT_DIR" && pwd)"
mkdir -p "$DIR/$OUTPUT_DIR"
OUTPUT_ABS="$(cd "$DIR/$OUTPUT_DIR" && pwd)"

docker run --rm --platform "$PLATFORM" \
  -v "$INPUT_ABS:/input" \
  -v "$OUTPUT_ABS:/output" \
  "$IMAGE" \
  bash -c "xvfb-run -a ODAFileConverter /input /output $OUT_VERSION $OUT_TYPE $RECURSE $AUDIT > /output/log.txt 2>&1; echo EXIT_CODE:\$?"
