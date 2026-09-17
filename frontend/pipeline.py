"""업로드된 dwg 를 대조 결과 CSV 까지 끌고 가는 파이프라인.

    dwg ──ODAFileConverter──▶ dxf ──deckcheck──▶ 구역별_대조.csv

리포지토리의 `convert-dwg-to-dxf.sh` 는 ODAFileConverter 를 별도 Docker 컨테이너로
띄운다. 여기서는 그럴 수 없다 — 이 서버 자체가 컨테이너 안이고 Docker 를 또
띄울 수 없다. 대신 변환기를 같은 이미지에 넣고 바이너리를 직접 부른다.

ODAFileConverter 는 Qt GUI 앱이라 X 디스플레이가 있어야 한다. 화면이 없는
서버에서는 xvfb-run 으로 가상 디스플레이를 붙여 준다.

진행 상황은 on_progress 콜백으로 밖에 알린다. 서버는 그걸 SSE 로 흘린다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent

# 변환기는 폴더 단위로 동작한다. 파일 하나만 넘길 수 없어 입출력 폴더를 만든다.
ODA_BINARY = "ODAFileConverter"
ODA_ARGS = ("ACAD2018", "DXF", "0", "1")

# deckcheck 패키지가 있는 곳. 이미지에서는 여기로 복사해 둔다.
DECKCHECK_DIR = HERE / "deckcheck_pkg"
# 대조 상대가 되는 발주 엑셀.
EXCEL_DIR = HERE / "excel"

COMPARE_CSV = "구역별_대조.csv"

ProgressFn = Callable[[str, str], None]  # (step, message)


class PipelineError(RuntimeError):
    """파이프라인이 사용자에게 설명할 수 있는 형태로 실패했을 때."""


@dataclass
class PipelineResult:
    csv_path: Path
    dxf_path: Path
    dxf_bytes: int


def converter_available() -> bool:
    """이 환경에서 dwg 변환이 가능한가.

    로컬 맥에는 ODAFileConverter 가 없다. 서버가 뜨는 것 자체를 막지 않고,
    업로드 시점에 분명한 메시지로 알리기 위해 따로 확인한다.
    """
    return shutil.which(ODA_BINARY) is not None


def _convert(dwg: Path, workdir: Path, progress: ProgressFn) -> Path:
    in_dir = workdir / "dwg"
    out_dir = workdir / "dxf"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dwg, in_dir / dwg.name)

    progress("convert", f"{dwg.name} 변환 중")

    command = [ODA_BINARY, str(in_dir), str(out_dir), *ODA_ARGS]
    if shutil.which("xvfb-run"):
        # 화면 없는 서버. -a 는 비어 있는 디스플레이 번호를 알아서 고른다.
        command = ["xvfb-run", "-a", *command]

    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=600, check=False
        )
    except subprocess.TimeoutExpired:
        raise PipelineError(
            "도면 변환이 10분을 넘겨 중단했습니다. 도면이 너무 크면 "
            "로컬에서 dxf 로 변환한 뒤 파이프라인을 돌려 주세요."
        )

    produced = sorted(out_dir.glob("*.dxf"))
    if not produced:
        # 변환기는 실패해도 0 을 반환하는 경우가 있어 산출물로 판정한다.
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        raise PipelineError(
            "dwg 를 dxf 로 변환하지 못했습니다."
            + (f" 변환기 출력: {detail}" if detail else "")
        )
    return produced[0]


def _compare(dxf: Path, workdir: Path, progress: ProgressFn) -> Path:
    if not EXCEL_DIR.is_dir() or not any(EXCEL_DIR.glob("*.xls*")):
        raise PipelineError(
            f"대조할 발주 엑셀이 없습니다: {EXCEL_DIR}"
        )

    progress("compare", "일람표 대조 중")
    csv_path = workdir / COMPARE_CSV

    proc = subprocess.run(
        [
            sys.executable, "-m", "deckcheck",
            "--dxf", str(dxf),
            "--excel", str(EXCEL_DIR),
            "--csv", str(csv_path),
        ],
        cwd=str(DECKCHECK_DIR),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    if not csv_path.exists():
        detail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise PipelineError(
            "일람표 대조에 실패했습니다."
            + (f" 상세: {detail}" if detail else "")
        )
    return csv_path


def run(dwg: Path, workdir: Path, progress: ProgressFn) -> PipelineResult:
    """dwg 하나를 받아 대조 CSV 까지 만든다. 실패는 PipelineError 로 올린다."""
    if not converter_available():
        raise PipelineError(
            "이 서버에는 도면 변환기(ODAFileConverter)가 없습니다. "
            "배포 이미지에서만 동작합니다."
        )

    dxf = _convert(dwg, workdir, progress)
    csv_path = _compare(dxf, workdir, progress)
    return PipelineResult(
        csv_path=csv_path, dxf_path=dxf, dxf_bytes=dxf.stat().st_size
    )
