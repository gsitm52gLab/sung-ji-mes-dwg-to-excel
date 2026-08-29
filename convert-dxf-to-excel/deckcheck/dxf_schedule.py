"""DXF 일람표 → DeckRecord.

행 묶기를 정렬된 리스트의 인접 인덱스가 아니라 좌표로 한다.
인접 인덱스 방식은 표 사이에 텍스트가 하나만 끼어들어도
엉뚱한 행을 상·하부로 물어온다.
"""

from __future__ import annotations

import re
from collections import defaultdict

import ezdxf

from .models import Cell, DeckRecord, ScheduleParseError
from .normalize import (
    norm_camber,
    norm_lattice,
    norm_text,
    product_of,
    split_code,
)

SCHEDULE_LAYER = "TG-TABLE.TEX"
SYMBOL_RE = re.compile(r"^[A-Z]{1,4}\d[A-Z0-9]*$")
# 표준코드 'M10085-110' / 'T13106-210'. 일람표 행을 단면상세도 행과 가르는 표지다.
CODE_RE = re.compile(r"^[A-Z]\d{4,6}-\d+$")
Y_TOL = 5.0  # 같은 행으로 볼 y 오차 (표의 행 간격은 약 39~40)
ROW_SPAN = 60.0  # 기호행에서 상·하부행까지 인정할 최대 y 거리
SYMBOL_ROW_COLS = 6  # 기호행 컬럼 수: 기호/두께/표준코드/래티스/캠버/서포트


def collect_texts(dxf_path: str) -> list[tuple[float, float, str]]:
    """일람표 레이어의 TEXT/MTEXT를 좌표째로 수집."""
    doc = ezdxf.readfile(dxf_path)
    out: list[tuple[float, float, str]] = []
    for entity in doc.modelspace():
        kind = entity.dxftype()
        if kind not in ("TEXT", "MTEXT"):
            continue
        if entity.dxf.layer != SCHEDULE_LAYER:
            continue
        text = (entity.dxf.text if kind == "TEXT" else entity.text).strip()
        if text:
            out.append((float(entity.dxf.insert.x), float(entity.dxf.insert.y), text))
    return out


def build_rows(
    texts: list[tuple[float, float, str]],
) -> dict[float, list[tuple[float, float, str]]]:
    """y를 Y_TOL로 반올림해 묶고, 행 내부는 x 오름차순 정렬."""
    rows: dict[float, list[tuple[float, float, str]]] = defaultdict(list)
    for x, y, text in texts:
        rows[round(y / Y_TOL) * Y_TOL].append((x, y, text))
    return {y_key: sorted(items) for y_key, items in rows.items()}


def _neighbour_row(
    rows: dict[float, list[tuple[float, float, str]]],
    y_key: float,
    symbol_x: float,
    above: bool,
    warnings: list[str] | None = None,
    symbol: str = "",
) -> list[tuple[float, float, str]] | None:
    """기호행 기준 ROW_SPAN 이내에서 가장 가까운 위/아래 행.

    기호보다 왼쪽에 있는 텍스트는 다른 표의 것이므로 제외한다.
    같은 거리 내에 여러 행이 있으면 경고하고 가장 가까운 행을 반환한다.
    """
    candidates: list[tuple[float, list[tuple[float, float, str]]]] = []
    for other, items in rows.items():
        if other == y_key or abs(other - y_key) > ROW_SPAN:
            continue
        if (other > y_key) != above:
            continue
        cells = [cell for cell in items if cell[0] >= symbol_x]
        if not cells:
            continue
        candidates.append((other, cells))

    if not candidates:
        return None

    # 가장 가까운 행을 찾는다
    best = min(candidates, key=lambda x: abs(x[0] - y_key))

    # 같은 거리 내에 여러 행이 있으면 경고한다
    if len(candidates) > 1 and warnings is not None:
        side = "상부" if above else "하부"
        y_values = sorted([y for y, _ in candidates])
        warnings.append(
            f"기호 '{symbol}' {side} 피복: {len(candidates)}개 행 발견 y={y_values}"
        )

    return best[1]


def parse_records(
    texts: list[tuple[float, float, str]],
    warnings: list[str] | None = None,
) -> list[DeckRecord]:
    """수집된 텍스트에서 일람표 레코드를 뽑는다.

    일람표 행인지 여부는 '맨 왼쪽이 기호 패턴' + '표준코드 셀 존재' 둘로 판별한다.
    단면상세도 행(`M1008 | M1310 | M1313`)도 맨 왼쪽이 기호 패턴에 걸리므로
    컬럼 수만으로 거르면 표 양식 변경 경고에 노이즈가 섞인다.

    일람표 행으로 보이는데 컬럼 수가 다르면 `warnings`에 담고 건너뛴다.
    표 양식이 바뀐 것을 조용히 넘기지 않기 위해서다.
    """
    rows = build_rows(texts)
    records: list[DeckRecord] = []

    for y_key in sorted(rows, reverse=True):
        items = rows[y_key]
        if not items:
            continue
        symbol_x, _, symbol = items[0]
        if not SYMBOL_RE.match(symbol):
            continue
        if not any(CODE_RE.match(text) for _, _, text in items):
            continue
        if len(items) != SYMBOL_ROW_COLS:
            if warnings is not None:
                cells = [text for _, _, text in items]
                warnings.append(
                    f"y={y_key:.0f} 기호행 '{symbol}' 컬럼 수 {len(items)}"
                    f" (기대 {SYMBOL_ROW_COLS}): {cells}"
                )
            continue

        code_x, code_y, code = items[2]
        type_code, tg = split_code(code)
        code_loc = (code_x, code_y)

        def cell(index: int, normalizer=norm_text) -> Cell:
            x, y, raw = items[index]
            return Cell(raw, normalizer(raw), (x, y))

        fields = {
            "TYPE": Cell(code, type_code, code_loc),
            "THK.": cell(1),
            "래티스": cell(3, norm_lattice),
            "캠버": cell(4, norm_camber),
            "서포트": cell(5),
            "TG": Cell(code, tg, code_loc),
        }

        upper = _neighbour_row(rows, y_key, symbol_x, above=True, warnings=warnings, symbol=symbol)
        lower = _neighbour_row(rows, y_key, symbol_x, above=False, warnings=warnings, symbol=symbol)
        for name, row in (("상부피복", upper), ("하부피복", lower)):
            if row:
                x, y, raw = row[0]
                fields[name] = Cell(raw, norm_text(raw), (x, y))
            else:
                fields[name] = Cell("", "", None)

        records.append(
            DeckRecord(symbol=symbol, fields=fields, source=product_of(code))
        )

    return records


def load_all(
    dxf_path: str, warnings: list[str] | None = None
) -> list[DeckRecord]:
    """DXF 하나에서 일람표 전체(MEGA + TERA)를 읽는다.

    하나도 못 찾으면 조용히 빈 결과를 주지 않고 예외를 던진다.
    레이어명이 바뀌었거나 일람표가 없는 도면이라는 뜻이다.
    """
    records = parse_records(collect_texts(dxf_path), warnings)
    if not records:
        raise ScheduleParseError(
            f"{dxf_path}: '{SCHEDULE_LAYER}' 레이어에서 일람표를 찾지 못했습니다"
        )
    return records
