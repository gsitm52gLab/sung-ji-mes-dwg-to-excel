#!/usr/bin/env python3
"""emit_order.py — 도면 → Sheet1(부재 단위) → 제작의뢰서(구간 합계) 를 구역별로 만든다.

제작의뢰서는 부재를 (구간, 길이) 로 합산한 결과다. 도면에서 직접 합계를
맞추려던 시도는 6/54 에 그쳤는데, 중간 단계인 Sheet1 을 거치면 부재가 1:1 로
대응되므로 경로가 열린다.
"""

from __future__ import annotations

import glob
import os
import sys
from collections import defaultdict

from openpyxl import Workbook, load_workbook

import deckreport as R
import poc_deckorder as M
from emit_sheet1 import has_sheet1, zone_of
from deckconfig import cfg
from deckcheck.models import ORDER_HEADER


def excel_sheet1_counts(path):
    """엑셀 Sheet1 → (구간, SLAB, 길이) -> 장수. 상한 측정용.

    도출된 규칙: 합계 − 강판 = ΣP + Σ(M, N),  강판 = ΣL
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        agg = defaultdict(int)
        zones = set()

        def num(r, i):
            try:
                return int(float(r[i])) if r[i] is not None else 0
            except (TypeError, ValueError):
                return 0

        for r in wb["Sheet1"].iter_rows(values_only=True):
            if len(r) < 33 or not r[0]:
                continue
            try:
                length = int(float(r[10]))
            except (TypeError, ValueError):
                continue
            zone = str(r[0]).strip()
            slab = norm_slab(str(r[2]).strip())
            agg[(zone, slab, length)] += num(r, 15) + num(r, 12) + num(r, 13)
            zones.add(zone.split("-")[0])
        return agg, zones
    finally:
        wb.close()


# 도면 DskNameLay 표기 → 발주서 SLAB NAME.
# Sheet1 의 DS4 가 제작의뢰서에서는 DS3S 로 적힌다 (엑셀 자체 데이터로 확인).
SLAB_MAP = {"DS3s": "DS3S", "IDS3s": "IDS3S", "DS4": "DS3S"}


def norm_slab(name):
    return SLAB_MAP.get(name, name)


def roll_zone(zone):
    """도면의 3단계 구간 코드를 발주서의 2단계로 접는다.

    도면에는 '사-1-1' ~ '사-1-9', '사-2-1' ~ '사-2-5' 처럼 한 단계 더 쪼갠
    라벨이 있는데, 발주서는 '사-1' / '사-2' 까지만 쓴다.
    """
    parts = zone.split("-")
    return "-".join(parts[:2]) if len(parts) > 2 else zone



# DECK_CTT 괄호값은 Sheet1 의 AG 이고, AG = 잔여(AC) + 60 이다.
# 그리고 발주 장수 P 는 잔여가 500 이상이면 도면 장수보다 1 크다
# (Sheet1 110 행 중 109 행에서 성립).
REMAINDER_OFFSET = 60
PARTIAL_THRESHOLD = 500


def order_count(count, remainder):
    """도면 장수(AF) → 발주 장수(P). 남는 폭이 500 이상이면 한 장이 더 든다."""
    return count + (1 if remainder - REMAINDER_OFFSET >= PARTIAL_THRESHOLD else 0)


def build(assigned, names, master, prefix):
    """배정 결과 → 제작의뢰서 행.

    합산 단위는 (구간, 길이) 가 아니라 (구간, SLAB, 길이) 다. 한 구간의 같은
    길이에 데크 종류가 둘 이상 섞이는 경우가 있어(마-1 의 DS3 39장 / DS3S 13장),
    길이만으로 묶으면 두 행이 하나로 뭉개진다.
    """
    agg = defaultdict(int)
    for zone, ps in assigned.items():
        if zone.split("-")[0] != prefix:
            continue
        for x, y, length, count, rem in ps:
            slab = norm_slab(M.nearest((x, y), names) or "")
            agg[(roll_zone(zone), slab, length)] += order_count(count, rem)

    rows = []
    for (zone, slab, length) in sorted(agg):
        m = master.get(slab) or master.get(slab.upper()) or {}
        typ = m.get("TYPE") or ""
        total = agg[(zone, slab, length)]
        rows.append([
            zone, None, slab, typ[1:] or None, m.get("TG"),
            m.get("하부피복"), m.get("캠버"), length, total,
            f"{typ}-{m.get('TG')}" if typ else None,
            round(total * length / 1000 * M.DECK_WIDTH_M, 3),
        ])
    return rows


def write(rows, path):
    wb = Workbook()
    ws = wb.active
    ws.title = "제작의뢰서"
    ws.append(list(ORDER_HEADER))
    for r in rows:
        ws.append(r)
    wb.save(path)


def main():
    os.makedirs(cfg.by_zone_dir, exist_ok=True)
    polys, div, labels, pieces, names, dcns = M.extract_shop(cfg.shop_dxf)
    assigned = M.strat_divider_cells(polys, div, labels, pieces)
    master = M.load_type_master(cfg.detail_dxf)
    oracle = M.load_oracle(cfg.excel_glob)

    paths = [p for p in sorted(glob.glob(cfg.excel_glob))
             if not os.path.basename(p).startswith("~$")]

    R.heading("구역별 제작의뢰서")
    t = R.table("구역", "엑셀의뢰행", "도면의뢰행", "도면일치", "엑셀S1상한", "파일")
    tot = hit = 0
    for path in paths:
        zone = zone_of(path)
        prefix = zone.split("-")[-1]
        rows = build(assigned, names, master, prefix)
        out = os.path.join(cfg.by_zone_dir, f"제작의뢰서_{zone}.xlsx")
        write(rows, out)

        truth = [r for r in oracle if r["구간"].split("-")[0] == prefix]
        mine = {(r[0], r[2], r[7]): r[8] for r in rows}
        ok = sum(1 for r in truth
                 if mine.get((r["구간"], r["SLAB"], r["길이"])) == r["합계"] - r["강판"])

        ceiling = R.blank()
        if has_sheet1(path):
            agg, zs = excel_sheet1_counts(path)
            if prefix in zs:
                c = sum(1 for r in truth
                        if agg.get((r["구간"], r["SLAB"], r["길이"]))
                        == r["합계"] - r["강판"])
                ceiling = R.ratio(c, len(truth))

        tot += len(truth); hit += ok
        t.add_row(zone, str(len(truth)), str(len(rows)),
                  R.ratio(ok, len(truth)), ceiling, os.path.basename(out))
    R.console.print(t)

    R.summary(f"합계 {hit}/{tot} 행 일치 ({hit/tot*100:.0f}%)")
    R.footnote("엑셀S1상한 = 엑셀 자신의 Sheet1 을 합산했을 때의 일치율. "
               "이 값이 낮으면 도면이 아니라 합산 규칙이 부족한 것이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
