#!/usr/bin/env python3
"""emit_*.py 콘솔 출력 공용 모듈.

한글은 터미널에서 두 칸을 차지하는데 파이썬 f-string 의 폭 지정자는 문자 수로
센다. 그래서 `f"{'구역':<7s}"` 로 맞춘 표는 한글이 섞이는 순간 어긋난다.
rich 는 East Asian Width 를 반영해 폭을 계산하므로 정렬이 맞는다.

컬럼은 여기 COLUMNS 한 곳에서만 정의한다. 스크립트는 이름만 넘긴다.

이름 규칙: `엑셀*` 는 발주 엑셀에서 읽은 값, `도면*` 는 도면에서 뽑은 값이다.
꼬리말은 세는 입도를 뜻한다 — `*부재` 는 엑셀 `Sheet1` 입도(한 행 = 부재 하나),
`*의뢰행` 은 엑셀 `제작의뢰서` 입도(한 행 = 구간·SLAB·길이 합산 하나)다.
제작의뢰서는 Sheet1 을 합산한 결과라 같은 구역이라도 `*의뢰행` 이 언제나 더 적다.
입도가 다른 값에 같은 이름을 붙이지 않는 것이 이 표의 요점이다. 반대로 값이
같으면 어느 스크립트에서든 이름도 같아야 한다 — emit_areas 와 emit_order 의
`도면의뢰행` 은 같은 수다.

엑셀/도면 접두어는 양쪽에서 같은 것을 세는 컬럼에만 붙인다. `구간`, `장수`,
`기호`, `검사셀` 처럼 한쪽에만 있는 값은 접두어 없이 쓴다.

    heading("구역별 발주 엑셀")
    t = table("구역", "구간", "장수", "대조", "파일")
    t.add_row("사", "10", "806", ratio(8, 17, "행 일치"))
    console.print(t)
"""

from __future__ import annotations

import sys
from typing import NamedTuple

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

# 파이프로 넘길 때 rich 는 폭을 80 으로 잡아 표를 접는다. 넉넉히 준다.
_PIPED_WIDTH = 200

console = Console(
    width=None if sys.stdout.isatty() else _PIPED_WIDTH,
    highlight=False,
)


class Col(NamedTuple):
    justify: str = "right"
    style: str | None = None


# 콘솔 표 컬럼 정의. 네 스크립트가 쓰는 컬럼을 전부 여기 모은다.
# 이름이 같으면 정렬·색도 같다는 것이 이 표의 요점이다.
COLUMNS: dict[str, Col] = {
    # 식별
    "구역": Col(justify="left", style="bold"),
    "파일": Col(justify="left", style="dim"),
    # 개수 — 부재 단위 (엑셀 `Sheet1` 입도, 한 행 = 부재 하나)
    "엑셀부재": Col(),
    "도면부재": Col(),
    # 개수 — 의뢰 단위 (엑셀 `제작의뢰서` 입도, 한 행 = 구간·SLAB·길이 합산 하나)
    "엑셀의뢰행": Col(),
    "도면의뢰행": Col(),
    # 개수 — 그 밖
    "구간": Col(),
    "장수": Col(),
    "기호": Col(),
    "검사셀": Col(),
    # 일치율 (ratio() 로 채운다)
    "일치": Col(),
    "불일치": Col(),
    "도면일치": Col(),
    "부재일치": Col(),
    "구간일치": Col(),
    "엑셀S1상한": Col(),
    "대조": Col(justify="left"),
    # 자유 문구
    "비고": Col(justify="left", style="yellow"),
}

_DEFAULT = Col()


def table(*headers: str) -> Table:
    """COLUMNS 정의를 적용한 마크다운 표를 만든다.

    제목은 표 안에 넣지 않는다. rich 가 제목 줄을 표 폭에 맞춰 공백으로 채우는
    바람에, 표를 그대로 복사해 마크다운에 붙이면 제목이 표 블록 안으로 딸려
    들어간다. 제목은 heading() 으로 표 위에 따로 찍는다.
    """
    t = Table(
        box=box.MARKDOWN,
        header_style="bold cyan",
    )
    for header in headers:
        col = COLUMNS.get(header, _DEFAULT)
        t.add_column(header, justify=col.justify, style=col.style)
    return t


def ratio(hit: int, total: int, suffix: str = "") -> Text:
    """`8/17` 일치 셀. 전부 일치는 초록, 하나도 못 맞추면 빨강."""
    if total == 0:
        return Text("—", style="dim")
    style = "green" if hit == total else "red" if hit == 0 else "yellow"
    label = f"{hit}/{total}"
    if suffix:
        label = f"{label} {suffix}"
    return Text(label, style=style)


def note(text: str, style: str = "dim") -> Text:
    """표 안에 들어가는 자유 문구 셀. 마크업으로 해석되지 않는다."""
    return Text(text, style=style)


def blank() -> Text:
    return Text("—", style="dim")


def heading(text: str) -> None:
    """표 위에 붙이는 소제목. 앞에 빈 줄을 하나 둔다."""
    console.print()
    console.print(Text(text, style="bold"))


def detail(text: str, mark: str = "✗", style: str = "red") -> None:
    """표 아래 상세 줄. 원본 값이 그대로 들어가므로 마크업을 끈다."""
    console.print(Text(f"    {mark} {text}", style=style))


def summary(text: str) -> None:
    console.print()
    console.print(Text(text, style="bold"))


def footnote(text: str) -> None:
    console.print(Text(text, style="dim"))
