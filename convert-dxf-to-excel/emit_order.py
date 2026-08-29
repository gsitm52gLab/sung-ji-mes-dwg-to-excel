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



# DECK_CTT 괄호값은 Sheet1 의 AG 이고, AG = 잔여(AC) + 60 이다. 이 값 하나가
# 그 부재를 어떻게 마감하는지를 정한다. 현 6개 발주서 Sheet1 110행 전수 일치:
#
#   AG >= 560   잔여 500 이상. 폭을 더 줄일 수 없어 정폭 데크를 한 장 더 쓴다.
#               → P = 장수 + 1,  M/N 없음,  강판 없음          (63행)
#   AG == 60    잔여 0. 딱 떨어지므로 강판(L) 한 장으로 마감한다.
#               → P = 장수,      M/N 없음,  강판 1             (18행)
#   그 밖       어중간한 자투리 폭. 이를 메우는 부재(M/N)가 한 장 든다.
#               → P = 장수,      M/N 1,     강판 없음          (29행)
#
# 제작의뢰서와 맞춰 보는 키는 `합계 - 강판` 이고 그 값은 ΣP + Σ(M,N) 이다.
# 즉 발주 장수에는 P 뿐 아니라 자투리 부재 M/N 도 포함된다 — 예전에는 P 만 세어
# 자투리가 있는 29행이 통째로 한 장씩 모자랐다.
#
# 잔여 판정은 AC 셀이 아니라 AG(괄호값)로 한다. 두 값은 보통 AG = AC + 60 이지만
# 마-6 DS2 행은 AG=6 / AC=546 으로 어긋나 있고, 실제 발주는 AG 쪽과 맞는다.
EXACT_REMAINDER = 60  # 잔여 0 — 딱 떨어져 강판으로 마감

# 구간당 분할선이 이 값보다 적으면 도면에 구간 경계가 사실상 안 그려진 것으로
# 본다. 그런 구역은 부재가 최근접 라벨로 흩어져 일치율이 떨어지는데, 이는 배정
# 알고리즘의 한계가 아니라 입력 도면의 결손이다.
# 측정(B1F): 마 9/7·바 3/4·사 6/9 는 82~100% 를 내지만, B 는 1/9 에 33% 다.
SPARSE_DIVIDER_RATIO = 0.25


def order_count(count, remainder):
    """도면 (장수 AF, 잔여 AG) → 발주 장수 (= P + M + N).

    한 장 더 쓰는 몫(P)과 자투리를 메우는 몫(M/N)은 서로 배타적이라, 딱
    떨어지지만 않으면 어느 쪽이든 정확히 한 장이 붙는다. 그래서 560 경계는
    P 냐 M/N 이냐를 가를 뿐 합계에는 영향이 없어 여기서는 따지지 않는다.
    """
    if remainder == EXACT_REMAINDER:
        return count
    return count + 1


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
    # 층별 평면도가 나란히 놓여 있고 구간 이름이 겹치므로 층을 갈라 배정한다.
    shop = M.load_shop_cached(cfg.shop_dxf)
    by_floor = {
        floor: (M.strat_divider_cells(po, dv, lb, pc), nm)
        for floor, (po, dv, lb, pc, nm, dc) in shop.items()
    }
    # 구간 배정의 근거가 도면에 얼마나 있는지 — 낮은 일치율의 원인 구분용
    density = {floor: M.divider_density(dv, lb)
               for floor, (po, dv, lb, pc, nm, dc) in shop.items()}
    master = M.load_type_master(cfg.detail_dxf)
    oracle = M.load_oracle(cfg.excel_glob)

    paths = [p for p in sorted(glob.glob(cfg.excel_glob))
             if not os.path.basename(p).startswith("~$")]

    R.heading("구역별 제작의뢰서")
    t = R.table("구역", "엑셀의뢰행", "도면의뢰행", "도면일치", "엑셀S1상한",
                "분할선", "파일")
    sparse = []
    tot = hit = 0
    for path in paths:
        zone = zone_of(path)
        floor, prefix = zone.split("-", 1)
        if floor not in by_floor:
            raise KeyError(f"도면에 {floor} 층이 없습니다. 있는 층: {sorted(by_floor)}")
        assigned, names = by_floor[floor]
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

        n_div, n_zone = density[floor].get(prefix, (0, 0))
        ratio = n_div / n_zone if n_zone else 0
        thin = n_zone > 1 and ratio < SPARSE_DIVIDER_RATIO
        if thin:
            sparse.append((zone, n_div, n_zone))

        tot += len(truth); hit += ok
        t.add_row(zone, str(len(truth)), str(len(rows)),
                  R.ratio(ok, len(truth)), ceiling,
                  R.note(f"{n_div}/{n_zone}", style="red" if thin else
                         "yellow" if ratio < 0.5 else "green"),
                  os.path.basename(out))
    R.console.print(t)

    R.summary(f"합계 {hit}/{tot} 행 일치 ({hit/tot*100:.0f}%)")
    if sparse:
        R.heading("도면 경계 부족 — 구간 배정 근거가 없는 구역")
        for zone, n_div, n_zone in sparse:
            R.detail(f"{zone}: 구간 {n_zone}개에 분할선 {n_div}개. 부재가 최근접 "
                     f"라벨로 흩어진다 — 코드가 아니라 도면에 경계를 그려야 한다.",
                     mark="⚠", style="yellow")
        R.console.print()
    R.footnote("분할선 = 그 구역의 (분할선 수 / 구간 수). `@@@구간` 레이어의 이 선이 "
               "구간을 가르는 유일한 근거다.")
    R.footnote("엑셀S1상한 = 엑셀 자신의 Sheet1 을 합산했을 때의 일치율. "
               "이 값이 낮으면 도면이 아니라 합산 규칙이 부족한 것이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
