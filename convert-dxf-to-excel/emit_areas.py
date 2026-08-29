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
import orderbook
from emit_order import (SPARSE_DIVIDER_RATIO, decompose, decompose_one,
                        norm_slab, order_count,
                        roll_zone, spec_fields)
from emit_sheet1 import zone_of
from deckcheck.dxf_schedule import load_all
from deckcheck.models import CONSTANT_COLUMNS, EXCEL_HEADER

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
                "x": x, "y": y,
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
    """부재 → 제작의뢰서 행. (구간, SLAB, 길이) 로 합산한다.

    한 행에 부재가 여럿 묶이면 도면NO 도 여럿인데, 발주서는 그중 가장 작은
    번호를 적는다 (합계가 맞은 행 기준 첫 부재 57% → 최소값 86%).
    """
    grouped = defaultdict(list)
    dcns = defaultdict(list)
    for p in pieces:
        key = (p["구간"], p["SLAB"], p["길이"])
        grouped[key].append((p["장수"], p["잔여"]))
        if p["도면NO"] is not None:
            dcns[key].append(p["도면NO"])
    dcn = {k: min(v) for k, v in dcns.items()}

    rows = []
    for key in sorted(grouped):
        zone, slab, length = key
        typ, tg, cover, camber, code = spec_fields(master, slab)
        plate, tg1, tg2, tg3 = decompose(grouped[key])
        total = plate + tg1 + tg2 + tg3
        rows.append({
            "구간": zone, "도면NO": dcn.get(key), "SLAB NAME": slab,
            "강판타입": CONSTANT_COLUMNS["강판타입"],
            "단부재": CONSTANT_COLUMNS["단부재"],
            "타입": typ, "높이": tg, "하부피복": cover, "캠버": camber,
            "길이": length, "강판": plate, "TG1": tg1, "TG2": tg2, "TG-2": 0,
            "TG3": tg3, "합계": total, "CODE": code,
            "면적": round((total - plate) * length / 1000 * M.DECK_WIDTH_M, 3),
        })
    return rows


def schedule_symbols(pieces, master, catalog):
    """일람표에 실을 기호. 목록(MEGA) 전체 + 이 구역이 실제로 쓰는 것.

    발주서 6개 모두 쓰지 않는 기호까지 포함해 MEGA 7종을 싣고 있다. 지붕처럼
    TERA 기호를 섞어 쓰는 구역은 그것도 함께 실어야 조회에 빠짐이 없다.
    """
    used = {p["SLAB"] for p in pieces if p["SLAB"] in master}
    return list(catalog) + sorted(used - set(catalog))


def write_area(area, pieces, master, catalog, path, truth=None, source=None):
    wb = Workbook()

    orders = order_rows(pieces, master)
    # 시트 순서는 발주서 원본과 같게 둔다: 제작의뢰서 / Sheet1 / RECHECK / 일람표.
    # 도면대조는 이 파이프라인이 덧붙이는 것이라 맨 뒤에 둔다.
    orderbook.write_order_sheet(wb.active, orders, cfg.order_info)

    orderbook.write_pieces_sheet(wb.create_sheet("Sheet1"), pieces, master,
                                 decompose_one)
    orderbook.write_recheck_sheet(wb.create_sheet("RECHECK"), orders)
    orderbook.write_schedule_sheet(wb.create_sheet("일람표"), EXCEL_HEADER,
                                   master,
                                   schedule_symbols(pieces, master, catalog),
                                   CONSTANT_COLUMNS)

    orderbook.write_compare_sheet(wb.create_sheet("도면대조"), orders, pieces,
                                  truth, source)

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
    # 일람표에 통째로 싣는 기호 목록. 발주 대상은 MEGA 계열이다.
    catalog = [r.symbol for r in load_all(cfg.detail_dxf) if r.source == "MEGA"]

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

    have = existing_orders()
    oracle = M.load_oracle(cfg.excel_glob)
    truth = defaultdict(dict)
    for r in oracle:
        key = floor_area(r["파일"])
        if key:
            truth[(key[0], M.area_of(r["구간"]))][
                (r["구간"], r["SLAB"], r["길이"])] = r["합계"] - r["강판"]

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
        n_rows = write_area(area, ps, master, catalog, path,
                            truth.get(key),
                            os.path.basename(have[key]) if key in have else None)
        qty = sum(p["발주장수"] for p in ps)
        zones = len({p["구간"] for p in ps})

        truth_area = truth.get(key)
        if truth_area:
            # 정답 키는 발주서의 `합계 - 강판` 이다. 생성 행도 같게 맞춘다.
            mine = {(r["구간"], r["SLAB NAME"], r["길이"]): r["합계"] - r["강판"]
                    for r in order_rows(ps, master)}
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
               f"  (구역당 파일 1개, 시트 5개: 제작의뢰서 / Sheet1 / RECHECK / 일람표 / 도면대조)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
