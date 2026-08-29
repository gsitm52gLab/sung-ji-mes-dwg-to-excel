#!/usr/bin/env python3
"""poc_deckorder.py — SHOP 도면에서 구간별 제작의뢰서를 뽑는 PoC.

구간에 부재를 배정하는 규칙이 아직 확정되지 않았다. 그래서 여러 배정 전략을
나란히 돌리고, 발주 엑셀 6개의 제작의뢰서 54행을 정답지로 점수를 매긴 뒤,
가장 잘 맞는 전략의 결과를 엑셀로 내보낸다.

PoC 이므로 테스트와 패키지 구조는 생략했다.

사용:
    python poc_deckorder.py
"""

from __future__ import annotations

import glob
import math
import os
import pickle
import re
import sys
from collections import defaultdict

import ezdxf
from openpyxl import Workbook, load_workbook

from deckconfig import cfg

# 입력 경로는 config.yaml(단일 진실 공급원)에서 온다.
# 도면 파일명·위치는 현장마다 다르므로 설정으로 분리한다.
SHOP_DXF = cfg.shop_dxf
DETAIL_DXF = cfg.detail_dxf
EXCEL_GLOB = cfg.excel_glob

ZONE_LAYER = "@@@구간"
PIECE_LAYER = "DECK_CTT"
NAME_LAYER = "DskNameLay"
DCN_LAYER = "NDS_DCN"

# 한 dxf 안에 층별 평면도가 가로로 나란히 놓여 있고, 구간 이름이 층 사이에서
# 겹친다 (지하1층 '마-1' 과 지붕 '마-1' 이 둘 다 존재). 층을 가르지 않으면
# 서로 다른 층의 부재가 한 구간으로 합산된다.
#
# 층 경계는 좌표 상수 대신 평면도 제목으로 잡는다. 제목은 각 평면도 한가운데
# 놓이므로, 엔티티를 x 가 가장 가까운 제목에 배정하면 평면도 단위로 갈린다.
PLAN_TITLE_LAYER = "AA-TEXT"

# 이 POC 가 채점하는 층. 정답지(load_oracle)가 B1F 발주서라 층도 B1F 여야 한다.
ORDER_FLOOR = "B1F"
PLAN_TITLE_RE = re.compile(r"(지하\s*(\d+)\s*층|지붕|옥탑|(\d+)\s*층).*?평면도")

# 'C', 'B' 처럼 하이픈 뒤 번호가 없는 것은 구역 전체를 가리키는 상위 라벨이라
# 배정 대상에서 뺀다. 제작의뢰서 행은 항상 'C-1' 형태다.
SUB_ZONE_RE = re.compile(r"^[^-]+-\d+")

# 같은 물리 구역을 층마다 다르게 적은 경우. 지하1층은 '가' 구역을 '1-1'~'1-3'
# 으로 적었는데 지붕은 같은 자리를 '가-1'~'가-3' 으로 적었다 (평면도 간격
# 338,050 만큼 겹쳐 보면 1-2↔가-2 가 3,902, 1-3↔가-3 이 3,426 밖에 안 떨어져
# 있고 구간 수도 3개로 같다. '1-n' 라벨은 지하1층에만 있다).
#
# 구간 이름은 도면 원본대로 두고 구역만 바로잡는다. 도면 라벨에만 적용하며
# 발주 엑셀에서 읽은 구간에는 쓰지 않는다 — 그쪽은 이미 제 이름을 쓴다.
AREA_ALIAS = {"B1F": {"1": "가"}}


def area_of(zone, floor=None):
    """구간 코드 → 구역. '사-1-3' → '사', 'B-4' → 'B', 지하1층 '1-2' → '가'.

    floor 를 주면 그 층의 표기 별칭을 적용한다. 안 주면 원문 그대로다.
    """
    area = zone.split("-")[0]
    return AREA_ALIAS.get(floor, {}).get(area, area)

# '3760mm^J10장 (260)'. 잔여값 '(260)' 은 없는 경우가 있어 선택으로 둔다.
PIECE_RE = re.compile(r"(\d+)\s*mm.*?(\d+)\s*장(?:.*?\((\d+)\))?")

# MTEXT 인라인 서식 '{\f굴림|b0|i0|c129|p50;장 }' 이 '장' 을 갈라놓는다.
MTEXT_FMT_RE = re.compile(r"\{\\[^;]*;|\}|\\[A-Za-z][^;\\]*;?")


def clean_mtext(text: str) -> str:
    """MTEXT 서식 코드를 걷어내고 본문만 남긴다."""
    return MTEXT_FMT_RE.sub("", text.replace("^J", " ")).strip()

DECK_WIDTH_M = 0.6  # 면적 = 장수 x 길이(m) x 0.6 — 제작의뢰서 54행 전수 검증됨


# ---------------------------------------------------------------------------
# 도면에서 원시 요소 뽑기
# ---------------------------------------------------------------------------

def signed_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def floor_name(title):
    """평면도 제목 → 짧은 층 이름. '지하1층 주차장 구조평면도' → 'B1F'.

    발주 엑셀 파일명이 'B1F-사' 형태라 그쪽 표기에 맞춘다.
    """
    m = PLAN_TITLE_RE.search(title)
    if not m:
        return None
    if m.group(2):
        return f"B{int(m.group(2))}F"
    if m.group(3):
        return f"{int(m.group(3))}F"
    return m.group(1)


def _plan_anchors(msp):
    """평면도 제목의 (x, 층 이름) 목록. 층 배정의 기준점이 된다."""
    anchors = []
    for e in msp:
        if e.dxftype() not in ("TEXT", "MTEXT") or e.dxf.layer != PLAN_TITLE_LAYER:
            continue
        text = (e.dxf.text if e.dxftype() == "TEXT" else e.text).strip()
        name = floor_name(text)
        if name:
            anchors.append((float(e.dxf.insert.x), name))
    return sorted(anchors)


def extract_shop_by_floor(path):
    """SHOP 도면 → {층 이름: (폴리곤, 분할선, 구간 라벨, 부재, 데크명, 도면번호)}.

    도면 읽기가 20초 가까이 걸리므로 한 번만 읽고 층별로 나눈다.
    부재가 하나도 없는 층(PIT·지하2층)은 결과에서 뺀다.
    """
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    anchors = _plan_anchors(msp)
    if not anchors:
        raise RuntimeError(
            f"{PLAN_TITLE_LAYER} 레이어에서 평면도 제목을 찾지 못했습니다: {path}")

    def floor_at(x):
        return min(anchors, key=lambda a: abs(a[0] - x))[1]

    groups = {name: ([], [], [], [], [], []) for _, name in anchors}
    bad_pieces = 0

    for e in msp:
        layer, kind = e.dxf.layer, e.dxftype()

        if layer == ZONE_LAYER and kind == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            if signed_area(pts) < 1.0:
                # 분할선은 조각마다 제 위치의 층에 넣는다
                for i in range(len(pts) - 1):
                    seg = (pts[i], pts[i + 1])
                    groups[floor_at((seg[0][0] + seg[1][0]) / 2)][1].append(seg)
            else:
                groups[floor_at(centroid(pts)[0])][0].append(pts)
            continue

        if kind not in ("TEXT", "MTEXT"):
            continue
        text = (e.dxf.text if kind == "TEXT" else e.text).strip()
        if not text:
            continue
        x, y = float(e.dxf.insert.x), float(e.dxf.insert.y)
        polys, dividers, labels, pieces, names, dcns = groups[floor_at(x)]

        if layer == ZONE_LAYER:
            labels.append((x, y, text))
        elif layer == PIECE_LAYER:
            m = PIECE_RE.search(clean_mtext(text))
            if m:
                pieces.append((x, y, int(m.group(1)), int(m.group(2)),
                               int(m.group(3)) if m.group(3) else 0))
            else:
                bad_pieces += 1
        elif layer == NAME_LAYER:
            names.append((x, y, text))
        elif layer == DCN_LAYER and text.isdigit():
            dcns.append((x, y, int(text)))

    if bad_pieces:
        print(f"⚠ {PIECE_LAYER} 파싱 실패 {bad_pieces}건", file=sys.stderr)
    return {name: g for name, g in groups.items() if g[3]}


def load_shop_cached(path):
    """extract_shop_by_floor 결과를 dxf 옆 sidecar(.cache.pkl)에 캐싱한다.

    shop dxf 는 100MB 를 넘어 파싱에 20초 가까이 걸린다. emit_areas/order/
    sheet1 이 저마다 파싱하는 대신, 첫 호출이 캐시를 만들고 이후는 즉시 읽는다.
    낡음 판정은 dxf 의 (mtime, size) 로 한다.

    캐시는 성능용일 뿐이라, 로드가 어떤 이유로 실패하든(없음·손상·구버전)
    그냥 다시 파싱한다 — 정답은 언제나 파싱이 낸다. 그래서 넓게 잡는다.
    """
    cache_path = path + ".cache.pkl"
    st = os.stat(path)
    key = [st.st_mtime, st.st_size]
    try:
        with open(cache_path, "rb") as f:
            blob = pickle.load(f)
        if blob["key"] == key:
            return blob["data"]
    except Exception:
        pass
    data = extract_shop_by_floor(path)
    tmp = f"{cache_path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "wb") as f:
            pickle.dump({"key": key, "data": data}, f)
        os.replace(tmp, cache_path)   # 원자적 교체 — 중단돼도 반쪽 캐시가 남지 않는다
    except Exception:
        # 캐시 저장 실패(권한·디스크)도 무시한다. 데이터는 이미 파싱으로 얻었으니
        # 캐시가 없을 뿐 결과는 정상이다. 남은 임시 파일만 지운다.
        try:
            os.remove(tmp)
        except OSError:
            pass
    return data


def extract_shop(path, floor):
    """층 하나를 골라 (폴리곤, 분할선, 구간 라벨, 부재, 데크명, 도면번호) 로 준다.

    층은 반드시 지정한다. 구간 이름이 층 사이에서 겹치므로 층을 합쳐 놓으면
    지붕 부재가 지하1층 구간으로 합산된다. 여러 층이 필요하면
    extract_shop_by_floor 를 쓴다.
    """
    by_floor = extract_shop_by_floor(path)
    if floor not in by_floor:
        raise KeyError(f"{floor} 층을 도면에서 찾지 못했습니다. "
                       f"있는 층: {sorted(by_floor)}")
    return by_floor[floor]


def divider_density(dividers, labels, floor=None):
    """구역 → (분할선 수, 구간 수). 구간 배정의 근거가 도면에 얼마나 있는지.

    strat_divider_cells 는 `@@@구간` 의 분할선으로 칸을 가른다. 구역에 구간이
    여럿인데 분할선이 없으면 가를 근거가 없어 부재가 최근접 라벨로 흩어진다.
    그때 낮게 나오는 일치율은 알고리즘 탓이 아니라 도면에 경계가 안 그려진
    탓이므로, 이 비율을 함께 보여 원인을 구분할 수 있게 한다.

    분할선은 중점에서 가장 가까운 하위 라벨의 구역에 속한 것으로 센다.
    """
    subs = _sub_labels(labels)
    zones = defaultdict(set)
    for l in subs:
        zones[area_of(l[2], floor)].add(l[2])
    counted = {area: [0, len(names)] for area, names in zones.items()}

    for d in dividers:
        mid = ((d[0][0] + d[1][0]) / 2, (d[0][1] + d[1][1]) / 2)
        name = nearest(mid, subs)
        if name:
            counted[area_of(name, floor)][0] += 1
    return {area: tuple(v) for area, v in counted.items()}


def load_type_master(path):
    """DETAIL 도면의 일람표 → {기호: 필드}. 타입/TG/피복/캠버를 여기서 가져온다."""
    from deckcheck.dxf_schedule import load_all

    return {
        rec.symbol: {k: c.value for k, c in rec.fields.items()}
        for rec in load_all(path)
    }


# ---------------------------------------------------------------------------
# 기하 유틸
# ---------------------------------------------------------------------------

def inside(pt, poly):
    x, y = pt
    n, c, j = len(poly), False, len(poly) - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def centroid(poly):
    return (sum(x for x, _ in poly) / len(poly), sum(y for _, y in poly) / len(poly))


def nearest(pt, candidates):
    """candidates 는 (x, y, payload). 가장 가까운 payload 를 준다."""
    if not candidates:
        return None
    return min(candidates, key=lambda c: math.dist(pt, (c[0], c[1])))[2]


# ---------------------------------------------------------------------------
# 배정 전략 — 전부 (polys, labels, pieces) -> {구간: [부재]} 인 순수 함수
# ---------------------------------------------------------------------------

def _sub_labels(labels):
    return [l for l in labels if SUB_ZONE_RE.match(l[2])]


def _ccw(a, b, c):
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])


def crosses(p, q, seg):
    """선분 pq 가 분할선 seg 를 가로지르는가."""
    a, b = seg
    return _ccw(p, a, b) != _ccw(q, a, b) and _ccw(p, q, a) != _ccw(p, q, b)


def _penned_labels(pt, polys, subs):
    """부재를 감싸는 가장 작은 폴리곤 안의 하위 라벨. 그런 폴리곤이 없으면 빈 목록.

    구획 폴리곤은 분할선처럼 crosses 로 안 걸리지만 엄연한 벽이다. 부재가 어느
    폴리곤에 갇혀 있으면 그 벽 밖 라벨은 후보에서 빠져야 한다.
    """
    best, best_area = None, None
    for poly in polys:
        if inside(pt, poly):
            a = signed_area(poly)
            if best_area is None or a < best_area:
                best, best_area = poly, a
    if best is None:
        return []
    return [l for l in subs if inside((l[0], l[1]), best)]


def strat_divider_cells(polys, dividers, labels, pieces):
    """부재를 최근접 라벨에 주되, 분할선과 구획 폴리곤 벽을 넘지 않는다.

    `@@@구간` 의 선 57개는 한 영역을 C-1 / C-2 처럼 나누는 칸막이다.
    부재와 라벨을 잇는 직선이 칸막이를 넘으면 다른 칸이라는 뜻이다.

    분할선이 안 그려진 경계는 구획 폴리곤이 대신 벽이 된다. 그래서 후보를 먼저
    부재가 갇힌 폴리곤 안의 라벨로 좁힌 뒤(벽 가드), 그 안에서 분할선을 넘지 않는
    최근접 라벨을 고른다. 품은 폴리곤이 없거나 그 안에 라벨이 없으면 전체 라벨로
    폴백한다(기존 동작).
    """
    subs = _sub_labels(labels)
    out = defaultdict(list)
    for p in pieces:
        pt = (p[0], p[1])
        cands = _penned_labels(pt, polys, subs) or subs
        reachable = [
            l for l in cands
            if not any(crosses(pt, (l[0], l[1]), d) for d in dividers)
        ]
        name = nearest(pt, reachable or cands)
        if name:
            out[name].append(p)
    return out


def strat_innermost(polys, dividers, labels, pieces):
    """부재를 감싸는 가장 작은 폴리곤의 라벨에 준다 — 부재당 정확히 한 구간.

    폴리곤이 중첩돼 있어 단순 포함 판정은 한 부재를 여러 구간에 중복 배정한다
    (334개 부재가 1578행으로 불어난다). 가장 안쪽 폴리곤만 인정해 1:1로 만든다.
    """
    labelled = []          # (면적, 폴리곤, 그 안의 라벨들)
    subs = _sub_labels(labels)
    for poly in polys:
        here = [l for l in subs if inside((l[0], l[1]), poly)]
        if here:
            labelled.append((signed_area(poly), poly, here))
    labelled.sort(key=lambda t: t[0])          # 작은 것부터

    out = defaultdict(list)
    for p in pieces:
        pt = (p[0], p[1])
        for _, poly, here in labelled:
            if inside(pt, poly):
                out[nearest(pt, here)].append(p)
                break                           # 가장 안쪽 하나만
    return out


def strat_label_polygon(polys, dividers, labels, pieces):
    """라벨이 들어 있는 폴리곤 안의 부재를 그 라벨에 준다."""
    out = defaultdict(list)
    for lx, ly, name in _sub_labels(labels):
        for poly in polys:
            if inside((lx, ly), poly):
                for p in pieces:
                    if inside((p[0], p[1]), poly):
                        out[name].append(p)
                break
    return out


def strat_nearest_label(polys, dividers, labels, pieces):
    """폴리곤을 무시하고 부재를 최근접 구간 라벨에 준다."""
    subs = _sub_labels(labels)
    out = defaultdict(list)
    for p in pieces:
        name = nearest((p[0], p[1]), subs)
        if name:
            out[name].append(p)
    return out


def strat_polygon_then_label(polys, dividers, labels, pieces):
    """폴리곤으로 1차 구획하고, 그 안에서 최근접 라벨로 세분한다.

    'C' 폴리곤 하나에 C-1 과 C-2 라벨이 함께 들어 있는 경우를 가른다.
    """
    subs = _sub_labels(labels)
    out = defaultdict(list)
    for poly in polys:
        here = [l for l in subs if inside((l[0], l[1]), poly)]
        if not here:
            continue
        for p in pieces:
            if inside((p[0], p[1]), poly):
                out[nearest((p[0], p[1]), here)].append(p)
    return out


def strat_merge_unlabeled(polys, dividers, labels, pieces):
    """라벨 없는 폴리곤을 가장 가까운 라벨 폴리곤에 병합한 뒤 배정한다.

    117개 폴리곤 중 71개가 라벨을 못 받는데, 그것들이 통째로 버려지는 것이
    수량이 모자라는 유력한 원인이다.
    """
    subs = _sub_labels(labels)
    owner = {}   # 폴리곤 index -> 구간명
    for i, poly in enumerate(polys):
        here = [l for l in subs if inside((l[0], l[1]), poly)]
        if here:
            owner[i] = here

    cents = {i: centroid(polys[i]) for i in range(len(polys))}
    for i in range(len(polys)):
        if i in owner:
            continue
        if not owner:
            continue
        j = min(owner, key=lambda k: math.dist(cents[i], cents[k]))
        owner[i] = owner[j]

    out = defaultdict(list)
    for i, poly in enumerate(polys):
        here = owner.get(i)
        if not here:
            continue
        for p in pieces:
            if inside((p[0], p[1]), poly):
                out[nearest((p[0], p[1]), here)].append(p)
    return out


def strat_nearest_label_capped(polys, dividers, labels, pieces):
    """최근접 라벨에 주되, 너무 먼 부재는 버린다 (다른 층/영역 혼입 방지)."""
    subs = _sub_labels(labels)
    out = defaultdict(list)
    for p in pieces:
        if not subs:
            break
        best = min(subs, key=lambda l: math.dist((p[0], p[1]), (l[0], l[1])))
        if math.dist((p[0], p[1]), (best[0], best[1])) <= 15000:
            out[best[2]].append(p)
    return out


STRATEGIES = {
    "innermost": strat_innermost,
    "divider_cells": strat_divider_cells,
    "label_polygon": strat_label_polygon,
    "nearest_label": strat_nearest_label,
    "polygon_then_label": strat_polygon_then_label,
    "merge_unlabeled": strat_merge_unlabeled,
    "nearest_capped": strat_nearest_label_capped,
}


# ---------------------------------------------------------------------------
# 정답지 — 발주 엑셀의 제작의뢰서 시트
# ---------------------------------------------------------------------------

def load_oracle(pattern):
    """제작의뢰서 시트 → [{구간, 도면NO, SLAB, 길이, 합계, 강판, 면적, CODE, 파일}]."""
    rows = []
    for path in sorted(glob.glob(pattern)):
        if os.path.basename(path).startswith("~$"):
            continue
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            if "제작의뢰서" not in wb.sheetnames:
                continue
            ws = wb["제작의뢰서"]
            for r in ws.iter_rows(min_row=15, values_only=True):
                if not r or len(r) < 18:
                    continue
                zone, dcn, slab = r[0], r[1], r[2]
                if not zone or not slab:
                    continue
                rows.append({
                    "파일": os.path.basename(path),
                    "구간": str(zone).strip(),
                    "도면NO": dcn,
                    "SLAB": str(slab).strip(),
                    "길이": int(r[9] or 0),
                    "강판": int(r[10] or 0),
                    "합계": int(r[15] or 0),
                    "CODE": r[16],
                    "면적": float(r[17] or 0),
                })
        finally:
            wb.close()
    return rows


# ---------------------------------------------------------------------------
# 채점
# ---------------------------------------------------------------------------

def score(assigned, oracle, pieces):
    """(구간, 길이) 입도로 채점한다. 오라클 행 키가 그 입도이기 때문이다."""
    got = defaultdict(int)
    for zone, ps in assigned.items():
        for _, _, length, count, _r in ps:
            got[(zone, length)] += count

    exact = 0
    err = 0
    diffs = []
    for row in oracle:
        key = (row["구간"], row["길이"])
        mine = got.get(key, 0)
        want = row["합계"] - row["강판"]
        if mine == want:
            exact += 1
        else:
            diffs.append((row["구간"], row["SLAB"], row["길이"], want, mine))
        err += abs(mine - want)

    # 부재는 (x, y, 길이, 장수, 잔여) 5-튜플이다. 좌표만 쓰므로 나머지는 버린다.
    used = len({(x, y) for ps in assigned.values() for x, y, *_ in ps})
    return {
        "정확행": exact,
        "총행": len(oracle),
        "장수오차": err,
        "미배정": len(pieces) - used,
        "구간수": len(assigned),
        "diffs": diffs,
    }


# ---------------------------------------------------------------------------
# 제작의뢰서 형태로 내보내기
# ---------------------------------------------------------------------------

HEADER = ["구간", "도면NO", "SLAB NAME", "강판", "단부재", "타입", "높이",
          "하부피복", "캠버", "길이", "강판n", "TG1", "TG2", "TG-2", "TG3",
          "합계", "CODE", "면적"]


def build_rows(assigned, names, dcns, master):
    """배정 결과 → 제작의뢰서 행. 타입/높이/피복/캠버는 일람표에서 채운다."""
    out = []
    for zone in sorted(assigned):
        agg = defaultdict(int)
        pos = {}
        for x, y, length, count, _r in assigned[zone]:
            agg[length] += count
            pos.setdefault(length, (x, y))
        for length in sorted(agg, reverse=True):
            x, y = pos[length]
            slab = nearest((x, y), names) or ""
            dcn = nearest((x, y), dcns)
            total = agg[length]
            m = master.get(slab) or master.get(slab.upper()) or {}
            type_code = (m.get("TYPE") or "")
            out.append([
                zone, dcn, slab,
                None,                       # 강판 — 도면에 없음
                None,                       # 단부재 — 도면에 없음
                type_code[1:] or None,      # 'M13135' -> '13135'
                m.get("TG"), m.get("하부피복"), m.get("캠버"),
                length,
                None, None, None, None, None,   # 강판n / TG 분해 — 도면에 없음
                total,
                f"{type_code}-{m.get('TG')}" if type_code else None,
                round(total * length / 1000 * DECK_WIDTH_M, 3),
            ])
    return out


def write_xlsx(rows, results, oracle, path):
    wb = Workbook()
    ws = wb.active
    ws.title = "제작의뢰서"
    ws.append(HEADER)
    for r in rows:
        ws.append(r)

    sh = wb.create_sheet("전략점수")
    sh.append(["전략", "정확행", "총행", "장수오차합", "미배정부재", "구간수"])
    for name, s in results.items():
        sh.append([name, s["정확행"], s["총행"], s["장수오차"], s["미배정"], s["구간수"]])

    sd = wb.create_sheet("구간별차이")
    sd.append(["전략", "구간", "SLAB NAME", "길이", "정답장수", "도면장수", "차이"])
    for name, s in results.items():
        for zone, slab, length, want, mine in s["diffs"]:
            sd.append([name, zone, slab, length, want, mine, mine - want])

    so = wb.create_sheet("정답지")
    so.append(["파일", "구간", "도면NO", "SLAB NAME", "길이", "강판", "합계", "CODE", "면적"])
    for r in oracle:
        so.append([r["파일"], r["구간"], r["도면NO"], r["SLAB"], r["길이"],
                   r["강판"], r["합계"], r["CODE"], r["면적"]])

    wb.save(path)


# ---------------------------------------------------------------------------

def main():
    print("도면 읽는 중…", file=sys.stderr)
    polys, dividers, labels, pieces, names, dcns = extract_shop(
        SHOP_DXF, ORDER_FLOOR)
    master = load_type_master(DETAIL_DXF)
    oracle = load_oracle(EXCEL_GLOB)
    print(f"  영역 {len(polys)} / 분할선 {len(dividers)} / 라벨 {len(labels)} "
          f"/ 부재 {len(pieces)} / 데크명 {len(names)} / 도면번호 {len(dcns)}",
          file=sys.stderr)
    print(f"  일람표 {len(master)}종 / 정답지 {len(oracle)}행", file=sys.stderr)

    results = {}
    for name, fn in STRATEGIES.items():
        assigned = fn(polys, dividers, labels, pieces)
        results[name] = score(assigned, oracle, pieces)
        results[name]["_assigned"] = assigned

    print(f"\n{'전략':<20s} {'정확행':>8s} {'장수오차':>10s} {'미배정':>8s} {'구간수':>7s}")
    for name, s in results.items():
        print(f"{name:<20s} {s['정확행']:>4d}/{s['총행']:<3d} "
              f"{s['장수오차']:>10d} {s['미배정']:>8d} {s['구간수']:>7d}")

    best = max(results, key=lambda n: (results[n]["정확행"], -results[n]["장수오차"]))
    print(f"\n최고 전략: {best}")

    rows = build_rows(results[best]["_assigned"], names, dcns, master)
    os.makedirs(cfg.poc_dir, exist_ok=True)
    out = os.path.join(cfg.poc_dir, "제작의뢰서_PoC.xlsx")
    for s in results.values():
        s.pop("_assigned", None)
    write_xlsx(rows, results, oracle, out)
    print(f"→ {out}  ({len(rows)}행)")


if __name__ == "__main__":
    main()
