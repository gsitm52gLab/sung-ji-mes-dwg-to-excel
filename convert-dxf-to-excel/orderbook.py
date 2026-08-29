#!/usr/bin/env python3
"""제작의뢰서 시트와 recheck 탭을 발주서 원본 서식으로 쓴다.

기존 emit 은 헤더 한 줄에 데이터만 얹은 단순한 표를 냈다. 실제 발주서는
14행짜리 머리말(발주 정보 · 강판타입/데크타입 참조표 · 집계 수식)을 두고
15행부터 데이터가 시작하며, 열도 A~R 로 정해져 있다. 그 배치를 그대로 쓴다.

recheck 탭은 이 파일을 열어 본 사람이 무엇을 다시 봐야 하는지 담는다.
기존 발주서가 있으면 행별 대조를, 없으면(지붕 전 구역) 도면 추적만 낸다.
"""

from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# 데이터 시작 행. 그 위 14행은 전부 머리말이다.
FIRST_DATA_ROW = 15
LAST_FORMULA_ROW = 185          # 원본이 수식에서 참조하는 범위 끝

# A~R 열 구성. 이름은 발주서 11~12행 머리말과 같다.
COLUMNS = [
    ("A", "구간"), ("B", "도면NO"), ("C", "SLAB NAME"),
    ("D", "강판타입"), ("E", "단부재"), ("F", "타입"),
    ("G", "높이"), ("H", "하부피복"), ("I", "캠버"),
    ("J", "길이"), ("K", "강판"), ("L", "TG1"), ("M", "TG2"),
    ("N", "TG-2"), ("O", "TG3"), ("P", "합계"), ("Q", "CODE"), ("R", "면적"),
]

# 머리말의 참조표. 발주서마다 같은 고정 표다.
PLATE_TYPES = [                                   # K~M: 강판타입
    ("MEGA", "A", "TG"), (None, "B", "TG-10"),
    ("GIGA", "A", "TG"), (None, "B", "TG-20"),
    (None, "C", "TG-40"), (None, "D", "TG-60"),
]
DECK_TYPES = [                                    # N~P: 데크타입
    ("MVR", "GVR", "일체형 RC"), ("MVS", "GVS", "일체형 S"),
    ("MVC", "GVC", "일체형 RC+S"), ("MVF", "GVF", "일체형 세이프"),
    ("MVFR", "GVFR", "일체형 세이프 & RC"), ("MVFS", "GVFS", "일체형 세이프 & S"),
]

# 좌측 발주 정보. (라벨 셀, 값 셀 병합범위) — 값은 config 의 order_info 에서 온다.
LEFT_INFO = [("업체명", 5), ("현장명", 6), ("담당자", 7), ("요청코드", 8)]
RIGHT_INFO = [("입고예정일", 5), ("하부받침대", 6), ("포장유무", 7), ("단부재유무", 8)]
# 발주서 원본의 라벨 표기 ('단부재유무' 는 원본에서 '단부재 유무')
LABEL_TEXT = {"단부재유무": "단부재 유무"}

# 머리말에 적히는 이름이 데이터 키와 다른 열
HEADER_TEXT = {"강판타입": "강판", "SLAB NAME": "SLAB\nNAME"}

COL_WIDTH = {"A": 18.8, "B": 4.8, "C": 7.8, "D": 5.8, "E": 6.8, "F": 8.8,
             "G": 5.8, "H": 7.8, "I": 7.8, "J": 10.8, "K": 5.8, "L": 5.8,
             "M": 5.8, "N": 5.8, "O": 5.8, "P": 6.8, "Q": 10.8, "R": 10.8,
             "S": 9.2, "T": 9.4}

_THIN = Side(style="thin")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEAD_FILL = PatternFill("solid", fgColor="DDEBF7")
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _put(ws, coord, value, *, bold=False, fill=False, box=True, center=True):
    c = ws[coord]
    c.value = value
    if bold:
        c.font = Font(bold=True)
    if fill:
        c.fill = _HEAD_FILL
    if box:
        c.border = _BOX
    if center:
        c.alignment = _CENTER
    return c


def write_header(ws, info, codes):
    """1~14행 머리말. codes 는 이 파일이 쓰는 CODE 목록(참조표 채움용)."""
    for col, w in COL_WIDTH.items():
        ws.column_dimensions[col].width = w

    # 제목. 원본은 단부재 첫 글자로 MEGA/GIGA/TERA 를 고르는 수식인데,
    # 단부재가 'MVS' 로 고정이라 결과는 항상 MEGA 다.
    t = _put(ws, "A1", "MEGA DECK 생산의뢰서", bold=True, box=False)
    t.font = Font(bold=True, size=16)
    ws.merge_cells("A1:J4")

    # 참조표 머리
    for coord, text in (("K1", "강판타입"), ("N1", "데크타입"),
                        ("Q1", "CODE"), ("R1", "면적"),
                        ("S1", "수량"), ("T1", "요청코드")):
        _put(ws, coord, text, bold=True, fill=True)
    ws.merge_cells("K1:M1")
    ws.merge_cells("N1:P1")

    for i, (grade, plate, tg) in enumerate(PLATE_TYPES):
        r = 2 + i
        if grade:
            _put(ws, f"K{r}", grade)
        _put(ws, f"L{r}", plate)
        _put(ws, f"M{r}", tg)
    ws.merge_cells("K2:K3")
    ws.merge_cells("K4:K7")

    for i, (mega, giga, desc) in enumerate(DECK_TYPES):
        r = 2 + i
        _put(ws, f"N{r}", mega)
        _put(ws, f"O{r}", giga)
        _put(ws, f"P{r}", desc, center=False)

    # CODE 별 면적·수량 집계. 원본은 배열 수식으로 CODE 를 뽑지만,
    # 이 파일이 쓰는 CODE 는 이미 알고 있으므로 그대로 적는다.
    last = LAST_FORMULA_ROW
    for i in range(6):
        r = 2 + i
        code = codes[i] if i < len(codes) else None
        _put(ws, f"Q{r}", code)
        _put(ws, f"R{r}", f"=SUMIF($Q${FIRST_DATA_ROW}:$Q${last},Q{r},"
                          f"$R${FIRST_DATA_ROW}:$R${last})")
        _put(ws, f"S{r}", f"=SUMIF($Q${FIRST_DATA_ROW}:$Q${last},Q{r},"
                          f"$P${FIRST_DATA_ROW}:$P${last})")

    # 발주 정보
    for label, r in LEFT_INFO:
        _put(ws, f"A{r}", label, bold=True, fill=True)
        _put(ws, f"B{r}", info.get(label), center=False)
        ws.merge_cells(f"B{r}:E{r}")
    for label, r in RIGHT_INFO:
        _put(ws, f"F{r}", LABEL_TEXT.get(label, label), bold=True, fill=True)
        ws.merge_cells(f"F{r}:H{r}")
        _put(ws, f"I{r}", info.get(label))
        ws.merge_cells(f"I{r}:J{r}")

    _put(ws, "K8", "총수량", bold=True, fill=True)
    ws.merge_cells("K8:M8")
    _put(ws, "N8", f"=SUM(K{FIRST_DATA_ROW}:O{last})")
    ws.merge_cells("N8:P8")
    _put(ws, "Q8", "총면적", bold=True, fill=True)
    _put(ws, "R8", f"=SUM(R{FIRST_DATA_ROW}:R{last})")
    ws.merge_cells("R8:T8")

    _put(ws, "A9", "추가 특이사항 또는 요청사항 기입란", center=False)
    ws.merge_cells("A9:T10")

    # 열 머리말 (11~12행). TYPE 은 D~I 6칸을 묶는 상위 머리말이다.
    for col, name in COLUMNS:
        if col in "DEFGHI":
            continue
        _put(ws, f"{col}11", HEADER_TEXT.get(name, name), bold=True, fill=True)
        ws.merge_cells(f"{col}11:{col}12")
    _put(ws, "D11", "TYPE", bold=True, fill=True)
    ws.merge_cells("D11:I11")
    for col, name in COLUMNS:
        if col in "DEFGHI":
            _put(ws, f"{col}12", HEADER_TEXT.get(name, name), bold=True, fill=True)
    _put(ws, "S11", "단열재", bold=True, fill=True)
    ws.merge_cells("S11:T11")
    _put(ws, "S12", "종류", bold=True, fill=True)
    _put(ws, "T12", "두께", bold=True, fill=True)

    # 소계 행
    for col in ("K", "L", "M", "N", "O", "P", "R"):
        _put(ws, f"{col}13",
             f"=SUBTOTAL(9,{col}{FIRST_DATA_ROW}:{col}{last})", bold=True)

    for r, h in ((1, 16.5), (2, 16.5), (3, 16.5), (4, 16.5), (5, 18.0),
                 (6, 18.0), (7, 18.0), (8, 18.0), (9, 18.0), (10, 18.0),
                 (11, 16.5), (12, 16.5), (14, 13.5)):
        ws.row_dimensions[r].height = h


def write_rows(ws, rows):
    """15행부터 데이터. rows 는 COLUMNS 이름을 키로 갖는 dict 목록이다."""
    for i, row in enumerate(rows):
        r = FIRST_DATA_ROW + i
        for col, name in COLUMNS:
            c = ws[f"{col}{r}"]
            c.value = row.get(name)
            c.border = _BOX
            if col in "ACEFQ":
                c.alignment = Alignment(horizontal="center")


def write_order_sheet(ws, rows, info):
    ws.title = "제작의뢰서"
    seen = []
    for row in rows:
        code = row.get("CODE")
        if code and code not in seen:
            seen.append(code)
    write_header(ws, info, seen)
    write_rows(ws, rows)
    ws.freeze_panes = f"A{FIRST_DATA_ROW}"


# ---------------------------------------------------------------------------
# recheck

RECHECK_COMPARE = ["구간", "SLAB NAME", "길이", "엑셀", "도면", "차이", "판정"]
RECHECK_TRACE = ["구간", "SLAB NAME", "길이", "도면NO", "x", "y",
                 "장수", "잔여", "발주"]


def _section(ws, r, title, header):
    c = _put(ws, f"A{r}", title, bold=True, box=False, center=False)
    c.font = Font(bold=True, size=12)
    for i, name in enumerate(header):
        _put(ws, f"{get_column_letter(1 + i)}{r + 1}", name, bold=True, fill=True)
    return r + 2


def write_recheck_sheet(ws, rows, pieces, truth, source):
    """recheck 탭. 위에 기존 발주서 대조, 아래에 도면 추적.

    truth 가 없으면(기존 발주서가 없는 구역) 대조는 사유만 적고 넘어간다.
    """
    ws.title = "recheck"
    for col, w in (("A", 10), ("B", 11), ("C", 8), ("D", 9), ("E", 12),
                   ("F", 12), ("G", 8), ("H", 8), ("I", 8)):
        ws.column_dimensions[col].width = w

    r = 1
    if truth is None:
        c = _put(ws, "A1", "[대조] 기존 발주서가 없어 대조를 생략한다.",
                 bold=True, box=False, center=False)
        c.font = Font(bold=True, size=12)
        r = 3
    else:
        r = _section(ws, 1, f"[대조] 기존 발주서: {source}", RECHECK_COMPARE)
        keys = sorted(set(truth) | {(x["구간"], x["SLAB NAME"], x["길이"])
                                    for x in rows})
        mine = {(x["구간"], x["SLAB NAME"], x["길이"]): x["합계"] - x["강판"]
                for x in rows}
        hit = 0
        for k in keys:
            e, d = truth.get(k), mine.get(k)
            if e is not None and e == d:
                verdict = "✓ 일치"; hit += 1
            elif e is None:
                verdict = "도면에만"
            elif d is None:
                verdict = "엑셀에만"
            else:
                verdict = "✗ 불일치"
            for i, v in enumerate([k[0], k[1], k[2], e, d,
                                   None if e is None or d is None else d - e,
                                   verdict]):
                _put(ws, f"{get_column_letter(1 + i)}{r}", v,
                     center=i not in (0, 1, 6))
            r += 1
        _put(ws, f"A{r}", f"{hit}/{len(truth)} 행 일치", bold=True,
             box=False, center=False)
        r += 3

    r = _section(ws, r, "[추적] 제작의뢰서 한 행이 어느 부재에서 왔나",
                 RECHECK_TRACE)
    for p in sorted(pieces, key=lambda p: (p["구간"], -p["길이"], p["도면NO"] or 0)):
        for i, v in enumerate([p["구간"], p["SLAB"], p["길이"], p["도면NO"],
                               round(p["x"]), round(p["y"]),
                               p["장수"], p["잔여"], p["발주장수"]]):
            _put(ws, f"{get_column_letter(1 + i)}{r}", v, center=i != 0)
        r += 1
