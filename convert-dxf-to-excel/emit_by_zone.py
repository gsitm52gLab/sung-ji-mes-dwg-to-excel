#!/usr/bin/env python3
"""emit_by_zone.py — 발주 엑셀 6개에 1:1 대응하는 도면 추출 일람표를 만든다.

각 발주 엑셀의 `일람표` 시트와 같은 기호 집합·같은 행 순서로,
도면에서 뽑은 값을 채운 엑셀을 구역별로 하나씩 생성한다.
그리고 원본과 셀 단위로 대조해 결과를 출력한다.
"""

from __future__ import annotations

import glob
import os
import re
import sys

from openpyxl import Workbook

from deckcheck.compare import MATCH, compare
from deckcheck.dxf_schedule import load_all
from deckcheck.excel_schedule import load_schedule
from deckcheck.models import CONSTANT_COLUMNS, EXCEL_HEADER
from deckcheck.report import write_csv
from deckconfig import cfg

# 파일명에서 구역을 집는다: '…_(MEGA)_B1F-C.xlsm' → 'B1F-C'
ZONE_RE = re.compile(r"(B1F-[^_.]+)")


def zone_of(path: str) -> str:
    m = ZONE_RE.search(os.path.basename(path))
    return m.group(1) if m else os.path.splitext(os.path.basename(path))[0][:20]


def write_zone_xlsx(records, dxf_by_symbol, path):
    """발주 엑셀의 기호 순서 그대로, 도면 값으로 채운 일람표를 쓴다."""
    wb = Workbook()
    ws = wb.active
    ws.title = "일람표"
    ws.append(list(EXCEL_HEADER))
    for rec in records:
        drawing = dxf_by_symbol.get(rec.symbol)
        row = [rec.symbol]
        for column in EXCEL_HEADER[1:]:
            if column in CONSTANT_COLUMNS:
                row.append(None)          # 도면에 없는 컬럼
            elif drawing is None:
                row.append(None)          # 도면에 없는 기호
            else:
                row.append(drawing.fields[column].value)
        ws.append(row)
    wb.save(path)


def main():
    os.makedirs(cfg.by_zone_dir, exist_ok=True)

    dxf_records = [r for r in load_all(cfg.detail_dxf) if r.source == "MEGA"]
    by_symbol = {r.symbol: r for r in dxf_records}
    print(f"도면 일람표(MEGA) {len(dxf_records)}종\n")

    paths = [p for p in sorted(glob.glob(cfg.excel_glob))
             if not os.path.basename(p).startswith("~$")]

    results = []
    print(f"{'구역':<10s} {'기호':>4s} {'검사셀':>7s} {'일치':>6s} {'불일치':>7s}  생성 파일")
    for path in paths:
        zone = zone_of(path)
        excel_records = load_schedule(path)
        out = os.path.join(cfg.by_zone_dir, f"일람표_{zone}.xlsx")
        write_zone_xlsx(excel_records, by_symbol, out)

        result = compare(excel_records, dxf_records, os.path.basename(path))
        results.append(result)
        matched = sum(1 for c in result.cells if c.verdict == MATCH)
        bad = len(result.mismatches)
        mark = "✓" if bad == 0 else "✗"
        print(f"{zone:<10s} {len(excel_records):>4d} {result.compared_count:>7d} "
              f"{matched:>6d} {bad:>7d}  {mark} {os.path.basename(out)}")
        for c in result.mismatches:
            print(f"    ✗ {c.symbol} {c.column}: 엑셀 {c.excel.value!r} ({c.excel.loc_str()}) "
                  f"↔ 도면 {c.dxf.raw!r} {c.dxf.loc_str()}" if c.dxf else
                  f"    ✗ {c.symbol} {c.column}: 도면에 기호 없음")
        for w in result.warnings:
            print(f"    ⚠ {w}")

    total_cells = sum(r.compared_count for r in results)
    total_bad = sum(len(r.mismatches) for r in results)
    print(f"\n합계: {len(results)}구역 / {total_cells}셀 검사 — 불일치 {total_bad}건")
    print(f"미검증 컬럼: {', '.join(CONSTANT_COLUMNS)} (도면에 해당 정보 없음)")

    csv_path = os.path.join(cfg.by_zone_dir, "구역별_대조.csv")
    write_csv(results, csv_path)
    print(f"→ 상세: {csv_path}")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
