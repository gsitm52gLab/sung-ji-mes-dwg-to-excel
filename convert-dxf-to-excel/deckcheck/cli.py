"""DeckCheck 명령줄 진입점."""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

from .compare import compare
from .dxf_schedule import load_all
from .excel_schedule import load_schedule as load_excel
from .models import HeaderMismatchError, SheetMissingError
from .report import print_summary, write_csv, write_schedule_xlsx

DEFAULT_DXF = "output/*.dxf"
DEFAULT_EXCEL = "excel/"
EXCEL_SUFFIXES = ("*.xlsm", "*.xlsx")


def _is_lock_file(path: str) -> bool:
    """Excel 이 통합문서를 열어둘 때 만드는 `~$이름.xlsm` 잠금 파일인가."""
    return Path(path).name.startswith("~$")


def _expand(patterns: list[str] | None, default: str, suffixes) -> list[str]:
    """경로/글롭/디렉터리를 모두 받아 파일 목록으로 편다.

    Excel 잠금 파일(`~$…`)은 통합문서가 아니므로 제외한다.
    """
    out: list[str] = []
    for pattern in patterns or [default]:
        path = Path(pattern)
        if path.is_dir():
            for suffix in suffixes:
                out.extend(sorted(str(p) for p in path.glob(suffix)))
        else:
            out.extend(sorted(glob.glob(pattern)))
    return [p for p in out if not _is_lock_file(p)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deckcheck",
        description="DXF 일람표와 엑셀 '일람표' 시트를 셀 단위로 대조합니다.",
    )
    parser.add_argument(
        "--dxf", nargs="*", help=f"DXF 경로/글롭/디렉터리 (기본 {DEFAULT_DXF})"
    )
    parser.add_argument(
        "--excel", nargs="*", help=f"엑셀 경로/글롭/디렉터리 (기본 {DEFAULT_EXCEL})"
    )
    parser.add_argument("--csv", help="상세 결과를 쓸 CSV 경로")
    parser.add_argument(
        "--emit", help="도면에서 뽑은 일람표를 엑셀 형태로 내보낼 경로"
    )
    parser.add_argument(
        "--product",
        default="MEGA",
        choices=["MEGA", "TERA"],
        help="대조할 제품 계열 (기본 MEGA)",
    )
    args = parser.parse_args(argv)

    dxf_paths = _expand(args.dxf, DEFAULT_DXF, ("*.dxf",))
    excel_paths = _expand(args.excel, DEFAULT_EXCEL, EXCEL_SUFFIXES)

    # 일람표가 실제로 파싱되는 DXF만 고른다. SHOP 도면이 섞여 있어도 된다.
    chosen: tuple[str, list] | None = None
    parse_warnings: list[str] = []
    for path in dxf_paths:
        warnings: list[str] = []
        try:
            records = load_all(path, warnings)
        except Exception as exc:  # 일람표 없음 / 읽기 실패 모두 건너뛴다
            print(f"⚠ {Path(path).name}: 건너뜀 ({exc})", file=sys.stderr)
            continue
        if any(r.source == args.product for r in records):
            chosen = (path, records)
            parse_warnings = warnings
            break

    if chosen is None:
        print(
            f"✗ {args.product} 일람표가 있는 DXF를 찾지 못했습니다: {dxf_paths}",
            file=sys.stderr,
        )
        return 2

    dxf_path, all_records = chosen
    dxf_records = [r for r in all_records if r.source == args.product]

    for warning in parse_warnings:
        print(f"⚠ 도면 표 양식 이상: {warning}", file=sys.stderr)

    # 도면만으로도 일람표를 뽑을 수 있어야 하므로, 비교 가능한 엑셀이
    # 하나도 없어 뒤에서 exit 2 로 끝나더라도 --emit 은 먼저 처리한다.
    if args.emit:
        write_schedule_xlsx(dxf_records, args.emit)
        print(f"  → 도면 일람표: {args.emit}")

    results = []
    for path in excel_paths:
        try:
            excel_records = load_excel(path)
        except SheetMissingError as exc:
            print(f"⚠ {exc}", file=sys.stderr)
            continue
        except HeaderMismatchError as exc:
            print(f"✗ {exc}", file=sys.stderr)
            return 2
        except Exception as exc:  # 손상/잠금/권한 등 읽기 자체가 실패한 경우
            print(f"⚠ {Path(path).name}: 읽기 실패로 건너뜀 ({exc})", file=sys.stderr)
            continue
        results.append(compare(excel_records, dxf_records, Path(path).name))

    if not results:
        print("✗ 비교 가능한 엑셀 파일이 없습니다", file=sys.stderr)
        return 2

    total_bad = print_summary(dxf_path, all_records, results)
    if args.csv:
        write_csv(results, args.csv)
        print(f"  → 상세: {args.csv}")

    return 0 if total_bad == 0 else 1
