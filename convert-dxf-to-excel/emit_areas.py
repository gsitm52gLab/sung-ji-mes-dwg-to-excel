#!/usr/bin/env python3
"""emit_areas.py — 도면 기준으로 구역별 발주 엑셀을 만든다.

고객 발주서는 구역 하나에 파일 하나이고, 그 안에 제작의뢰서 / Sheet1 / 일람표
시트가 들어 있다. 이 스크립트는 같은 규칙으로 도면에서 파일을 만든다.

앞선 스크립트들은 `excel/` 에 있는 발주서를 훑으며 그 구역만 처리했다.
그래서 발주서가 아직 없는 구역(가·다·라·아·자·카·1)은 산출되지 않았다.
여기서는 도면의 구간 라벨에서 구역 목록을 직접 뽑으므로 전 구역이 나온다.
발주서가 있는 구역은 대조 결과도 함께 출력한다.

사용:
    python3 emit_areas.py
"""

from __future__ import annotations

import glob
import os
import sys
from collections import defaultdict

from openpyxl import Workbook

import deckreport as R
import poc_deckorder as M
from deckconfig import cfg
from emit_order import (SPARSE_DIVIDER_RATIO, norm_slab, order_count,
                        roll_zone)
from emit_sheet1 import zone_of
from deckcheck.models import EXCEL_HEADER, ORDER_HEADER, PIECE_HEADER

# 발주 대상이 아닌 라벨. 단열 구간과 메모성 텍스트는 제작 부재가 아니다.
SKIP_AREAS = {"지붕", "B1F"}


def collect(assigned, names, dcns, floor=None):
    """배정 결과를 구역 → 구간 → 부재 로 정리한다."""
    areas = defaultdict(list)
    for zone, ps in assigned.items():
        rolled = roll_zone(zone)
        area = M.area_of(rolled, floor)
        if area in SKIP_AREAS or "-" not in rolled:
            continue
        for x, y, length, count, rem in ps:
            areas[area].append({
                "구간": rolled,
                "도면NO": M.nearest((x, y), dcns),
                "SLAB": norm_slab(M.nearest((x, y), names) or ""),
                "길이": length,
                "장수": count,
                "잔여": rem,
                "발주장수": order_count(count, rem),
            })
    return areas


def order_rows(pieces, master):
    """부재 → 제작의뢰서 행. (구간, SLAB, 길이) 로 합산한다."""
    agg = defaultdict(int)
    dcn = {}
    for p in pieces:
        key = (p["구간"], p["SLAB"], p["길이"])
        agg[key] += p["발주장수"]
        dcn.setdefault(key, p["도면NO"])

    rows = []
    for (zone, slab, length) in sorted(agg):
        m = master.get(slab) or {}
        typ = m.get("TYPE") or ""
        total = agg[(zone, slab, length)]
        rows.append([
            zone, dcn[(zone, slab, length)], slab,
            typ[1:] or None, m.get("TG"), m.get("하부피복"), m.get("캠버"),
            length, total,
            f"{typ}-{m.get('TG')}" if typ else None,
            round(total * length / 1000 * M.DECK_WIDTH_M, 3),
        ])
    return rows


def schedule_rows(pieces, master):
    """그 구역이 실제로 쓰는 데크 타입만 일람표로 낸다."""
    used = sorted({p["SLAB"] for p in pieces if p["SLAB"] in master})
    rows = []
    for slab in used:
        f = master[slab]
        rows.append([slab] + [
            None if col in ("단부재", "강판타입") else f.get(col)
            for col in EXCEL_HEADER[1:]
        ])
    return rows


def write_area(area, pieces, master, path):
    wb = Workbook()

    ws = wb.active
    ws.title = "제작의뢰서"
    ws.append(list(ORDER_HEADER))
    orders = order_rows(pieces, master)
    for r in orders:
        ws.append(r)

    s1 = wb.create_sheet("Sheet1")
    s1.append(list(PIECE_HEADER))
    for p in sorted(pieces, key=lambda p: (p["구간"], -p["길이"])):
        s1.append([p["구간"], p["도면NO"], p["SLAB"],
                   p["길이"], p["발주장수"], p["잔여"]])

    sc = wb.create_sheet("일람표")
    sc.append(list(EXCEL_HEADER))
    for r in schedule_rows(pieces, master):
        sc.append(r)

    wb.save(path)
    return len(orders)


def floor_area(name):
    """발주서 파일명 → (층, 구역). '…_(MEGA)_B1F-사.xlsm' → ('B1F', '사').

    zone_of 가 NFD 파일명 정규화까지 맡는다.
    """
    zone = zone_of(name)
    return tuple(zone.split("-", 1)) if "-" in zone else None


def existing_orders():
    """(층, 구역) → 기존 발주서 경로."""
    found = {}
    for p in sorted(glob.glob(cfg.excel_glob)):
        if os.path.basename(p).startswith("~$"):
            continue
        key = floor_area(os.path.basename(p))
        if key:
            found[key] = p
    return found


def main():
    os.makedirs(cfg.areas_dir, exist_ok=True)
    master = M.load_type_master(cfg.detail_dxf)

    # 층별 평면도가 나란히 놓여 있고 구간 이름이 층 사이에서 겹친다
    # (지하1층 '마-1' 과 지붕 '마-1'). 층을 갈라야 부재가 안 섞인다.
    shop = M.load_shop_cached(cfg.shop_dxf)
    areas = {}
    density = {}
    for floor, (po, dv, lb, pc, nm, dc) in shop.items():
        assigned = M.strat_divider_cells(po, dv, lb, pc)
        for area, ps in collect(assigned, nm, dc, floor).items():
            areas[(floor, area)] = ps
        # 구간을 가를 근거가 도면에 얼마나 있는지. 대조할 발주서가 없는 구역
        # (지붕 전체)에서는 이 값이 결과를 믿을 수 있는지 판단할 유일한 단서다.
        density[floor] = M.divider_density(dv, lb, floor)

    oracle = M.load_oracle(cfg.excel_glob)
    truth = defaultdict(dict)
    for r in oracle:
        key = floor_area(r["파일"])
        if key:
            truth[(key[0], M.area_of(r["구간"]))][
                (r["구간"], r["SLAB"], r["길이"])] = r["합계"] - r["강판"]

    have = existing_orders()
    R.console.print(f"도면 층 {len(shop)}개 / 구역 {len(areas)}개 "
                    f"/ 기존 발주서 {len(have)}개")

    R.heading("구역별 발주 엑셀")
    t = R.table("층", "구역", "구간", "분할선", "도면부재", "도면의뢰행",
                "장수", "대조", "파일")
    sparse = []
    tot = hit = 0
    for key in sorted(areas, key=lambda k: (k[0],
                                            -sum(p["발주장수"] for p in areas[k]))):
        floor, area = key
        ps = areas[key]
        path = os.path.join(cfg.areas_dir, f"{floor}-{area}.xlsx")
        n_rows = write_area(area, ps, master, path)
        qty = sum(p["발주장수"] for p in ps)
        zones = len({p["구간"] for p in ps})

        if key in truth:
            mine = {(r[0], r[2], r[7]): r[8] for r in order_rows(ps, master)}
            truth_area = truth[key]
            ok = sum(1 for k, v in truth_area.items() if mine.get(k) == v)
            tot += len(truth_area); hit += ok
            verdict = R.ratio(ok, len(truth_area), "행 일치")
        else:
            verdict = R.note("발주서 없음 — 신규", style="cyan")

        n_div, n_zone = density[floor].get(area, (0, 0))
        ratio = n_div / n_zone if n_zone else 0
        thin = n_zone > 1 and ratio < SPARSE_DIVIDER_RATIO
        if thin:
            sparse.append((floor, area, n_div, n_zone))

        t.add_row(floor, area, str(zones),
                  R.note(str(n_div), style="red" if thin else
                         "yellow" if ratio < 0.5 else "green"),
                  str(len(ps)), str(n_rows), str(qty),
                  verdict, os.path.basename(path))
    R.console.print(t)

    if sparse:
        R.heading("도면 경계 부족 — 구간 배정 근거가 없는 구역")
        for floor, area, n_div, n_zone in sparse:
            R.detail(f"{floor}-{area}: 구간 {n_zone}개에 분할선 {n_div}개. "
                     f"구간별 장수를 믿기 어렵다.", mark="⚠", style="yellow")

    R.summary(f"기존 발주서가 있는 구역: {hit}/{tot} 행 일치 ({hit/tot*100:.0f}%)")
    R.footnote("분할선 = `@@@구간` 레이어에서 그 구역의 구간을 가르는 선의 수. "
               "구간 수에 비해 적으면 부재가 최근접 라벨로 흩어진다.")
    R.footnote(f"→ {cfg.areas_dir}/"
               f"  (구역당 파일 1개, 시트 3개: 제작의뢰서 / Sheet1 / 일람표)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
