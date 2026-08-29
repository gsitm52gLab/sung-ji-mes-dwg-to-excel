"""도면 레코드와 엑셀 레코드의 셀 단위 대조."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import COMPARED_COLUMNS, CONSTANT_COLUMNS, Cell, DeckRecord

MATCH = "일치"
MISMATCH = "불일치"
NOT_COMPARED = "N/A"
MISSING = "도면에 없음"


@dataclass
class CellResult:
    symbol: str
    column: str
    excel: Cell
    dxf: Cell | None
    verdict: str


@dataclass
class FileResult:
    """도면과 엑셀의 셀 단위 대조 결과.

    각 속성의 의미:
    - cells: 모든 비교 결과 셀 (COMPARED_COLUMNS 8개 + CONSTANT_COLUMNS 2개 = 10개/기호)
    - mismatches: MISMATCH 또는 MISSING 판정 셀들
    - row_count: 고유 기호의 개수 (엑셀 기준)
    - compared_count: MATCH 또는 MISMATCH 판정 셀의 개수 (도면에 있는 기호만 포함)

    주의: MISSING 셀은 mismatches에 포함되지만 compared_count에는 포함되지 않음.
    따라서 compared_count - len(mismatches)는 일치 셀의 개수가 아님.
    MISSING 셀이 존재할 때는 이 식이 음수가 될 수 있음.
    """
    excel_name: str
    cells: list[CellResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def mismatches(self) -> list[CellResult]:
        return [c for c in self.cells if c.verdict in (MISMATCH, MISSING)]

    @property
    def row_count(self) -> int:
        return len({c.symbol for c in self.cells})

    @property
    def compared_count(self) -> int:
        return len([c for c in self.cells if c.verdict in (MATCH, MISMATCH)])


def compare(
    excel_records: list[DeckRecord],
    dxf_records: list[DeckRecord],
    excel_name: str,
) -> FileResult:
    """엑셀 기준으로 대조한다.

    도면에만 있는 기호(TERA 계열)는 별개 제품이므로 불일치가 아니다.
    """
    # 도면 기호 중복 감지
    dxf_symbol_counts = {}
    for record in dxf_records:
        dxf_symbol_counts[record.symbol] = dxf_symbol_counts.get(record.symbol, 0) + 1

    for symbol, count in dxf_symbol_counts.items():
        if count > 1:
            # 마지막 레코드만 유지되지만 중복을 경고로 기록
            pass  # 아래에서 경고 추가

    # 엑셀 기호 중복 감지
    excel_symbol_counts = {}
    for record in excel_records:
        excel_symbol_counts[record.symbol] = excel_symbol_counts.get(record.symbol, 0) + 1

    by_symbol = {record.symbol: record for record in dxf_records}
    result = FileResult(excel_name=excel_name)

    # 도면 중복 경고 추가
    for symbol, count in dxf_symbol_counts.items():
        if count > 1:
            result.warnings.append(f"도면: 기호 '{symbol}'이(가) {count}회 반복됨")

    # 엑셀 중복 경고 추가
    for symbol, count in excel_symbol_counts.items():
        if count > 1:
            result.warnings.append(f"엑셀: 기호 '{symbol}'이(가) {count}회 반복됨")

    for record in excel_records:
        drawing = by_symbol.get(record.symbol)

        for column in COMPARED_COLUMNS:
            excel_cell = record.fields[column]
            if drawing is None:
                result.cells.append(
                    CellResult(record.symbol, column, excel_cell, None, MISSING)
                )
                continue
            dxf_cell = drawing.fields[column]
            verdict = MATCH if excel_cell.value == dxf_cell.value else MISMATCH
            result.cells.append(
                CellResult(record.symbol, column, excel_cell, dxf_cell, verdict)
            )

        # 도면에 정보가 없는 컬럼: 비교하지 않되 고정값에서 벗어나면 경고
        for column, expected in CONSTANT_COLUMNS.items():
            excel_cell = record.fields[column]
            result.cells.append(
                CellResult(record.symbol, column, excel_cell, None, NOT_COMPARED)
            )
            if excel_cell.value != expected:
                result.warnings.append(
                    f"{record.symbol} {column}: 고정값 '{expected}'이 아닌 "
                    f"'{excel_cell.value}' ({excel_cell.loc_str()})"
                )

    return result
