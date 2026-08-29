"""대조 결과 출력: 콘솔 요약과 CSV 상세."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from openpyxl import Workbook

from .compare import MISSING, FileResult
from .models import CONSTANT_COLUMNS, EXCEL_HEADER, DeckRecord

CSV_HEADER = [
    "파일",
    "기호",
    "컬럼",
    "엑셀값",
    "엑셀셀",
    "도면원문",
    "도면정규화",
    "도면좌표",
    "판정",
]


def print_summary(
    dxf_path: str,
    dxf_records: list[DeckRecord],
    results: list[FileResult],
    stream=None,
) -> int:
    """파일별 한 줄 요약 + 불일치 상세. 총 불일치 건수를 반환한다.

    결과가 깨끗하면 짧게 끝나야 매번 돌려볼 만하다.
    """
    # 기본값 None은 모듈 임포트 시점에 고정되지 않도록, 함수 호출 시점에 평가된다.
    # stream=sys.stdout 을 기본값으로 쓰면 임포트 시점의 sys.stdout 객체로 고정되어
    # 이후 sys.stdout 변경(pytest capsys, redirect_stdout 등)을 무시한다.
    stream = sys.stdout if stream is None else stream
    mega = sum(1 for r in dxf_records if r.source == "MEGA")
    tera = sum(1 for r in dxf_records if r.source == "TERA")
    print(
        f"📐 도면: {Path(dxf_path).name}  (MEGA {mega}종 / TERA {tera}종)",
        file=stream,
    )
    print(file=stream)

    total_cells = 0
    total_rows = 0
    total_bad = 0

    for result in results:
        bad = result.mismatches
        total_cells += result.compared_count
        total_rows += result.row_count
        total_bad += len(bad)

        mark = "✓" if not bad else "✗"
        tail = "일치" if not bad else f"불일치 {len(bad)}"
        print(
            f"  {mark} {result.excel_name:<44s} {result.row_count}행  {tail}",
            file=stream,
        )

        for cell in bad:
            if cell.verdict == MISSING:
                detail = "도면에 해당 기호 없음"
            else:
                detail = f"도면 '{cell.dxf.raw}' {cell.dxf.loc_str()}"
            print(
                f"      {cell.symbol}  {cell.column}  "
                f"엑셀 '{cell.excel.value}' ({cell.excel.loc_str()})  ↔  {detail}",
                file=stream,
            )

        for warning in result.warnings:
            print(f"      ⚠ {warning}", file=stream)

    print(file=stream)
    print(
        f"  {len(results)}파일 / {total_rows}행 / {total_cells}셀 검사 "
        f"— 불일치 {total_bad}건",
        file=stream,
    )
    print(
        f"  ⚠ 미검증 컬럼: {', '.join(CONSTANT_COLUMNS)} (도면에 해당 정보 없음)",
        file=stream,
    )
    return total_bad


def write_csv(results: list[FileResult], csv_path) -> None:
    """불일치만이 아니라 전체 셀을 판정과 함께 기록한다.

    근거 자료로 남기려면 '틀린 게 없다'도 기록되어 있어야 한다.
    utf-8-sig 로 써야 엑셀에서 한글이 깨지지 않는다.
    """
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for result in results:
            for cell in result.cells:
                writer.writerow(
                    [
                        result.excel_name,
                        cell.symbol,
                        cell.column,
                        cell.excel.value,
                        cell.excel.loc_str(),
                        cell.dxf.raw if cell.dxf else "",
                        cell.dxf.value if cell.dxf else "",
                        cell.dxf.loc_str() if cell.dxf else "",
                        cell.verdict,
                    ]
                )


def write_schedule_xlsx(dxf_records: list[DeckRecord], xlsx_path) -> None:
    """도면에서 뽑은 일람표를 엑셀 `일람표` 시트와 같은 형태로 내보낸다.

    발주 엑셀과 나란히 놓고 볼 수 있도록 컬럼 구성을 EXCEL_HEADER 와 똑같이 맞춘다.
    도면에 정보가 없는 `단부재`/`강판타입`은 빈칸으로 둔다 — 임의값을 채우면
    도면에서 나온 값과 구분이 되지 않는다.
    """
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "일람표"
    sheet.append(list(EXCEL_HEADER))

    for record in dxf_records:
        row = [record.symbol]
        for column in EXCEL_HEADER[1:]:
            if column in CONSTANT_COLUMNS:
                row.append(None)  # 도면에 없는 컬럼
            else:
                row.append(record.fields[column].value)
        sheet.append(row)

    workbook.save(xlsx_path)
