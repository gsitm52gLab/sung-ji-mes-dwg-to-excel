"""DeckCheck 공통 데이터 모델과 상수."""

from __future__ import annotations

from dataclasses import dataclass, field

# 엑셀 `일람표` 시트 1행 헤더. 순서까지 이대로여야 한다.
EXCEL_HEADER: tuple[str, ...] = (
    "SLAB NAME",
    "TYPE",
    "THK.",
    "래티스",
    "캠버",
    "단부재",
    "서포트",
    "TG",
    "상부피복",
    "하부피복",
    "강판타입",
)

# 발주 엑셀 `제작의뢰서` 시트 1행 헤더. emit_areas / emit_order 가 함께 쓴다.
ORDER_HEADER: tuple[str, ...] = (
    "구간",
    "도면NO",
    "SLAB NAME",
    "타입",
    "높이",
    "하부피복",
    "캠버",
    "길이",
    "합계",
    "CODE",
    "면적",
)

# 발주 엑셀 `Sheet1` (부재 한 줄 = 한 행) 헤더. emit_areas / emit_sheet1 이 함께 쓴다.
PIECE_HEADER: tuple[str, ...] = (
    "구간",
    "도면NO",
    "SLAB NAME",
    "길이",
    "장수",
    "잔여",
)

# 도면과 실제로 대조하는 컬럼 (8개)
COMPARED_COLUMNS: tuple[str, ...] = (
    "TYPE",
    "THK.",
    "래티스",
    "캠버",
    "서포트",
    "TG",
    "상부피복",
    "하부피복",
)

# 도면에 정보가 없어 대조 불가한 컬럼 → 고정값 감시만 한다.
CONSTANT_COLUMNS: dict[str, str] = {"단부재": "MVS", "강판타입": "A"}


class DeckCheckError(Exception):
    """DeckCheck 전용 예외의 최상위."""


class ScheduleParseError(DeckCheckError):
    """도면에서 일람표를 찾지 못했다."""


class SheetMissingError(DeckCheckError):
    """엑셀에 `일람표` 시트가 없다."""


class HeaderMismatchError(DeckCheckError):
    """엑셀 `일람표` 시트의 헤더가 기대와 다르다."""


@dataclass(frozen=True)
class Cell:
    """비교 단위 하나. 원문(raw)을 끝까지 들고 다니는 것이 요점이다.

    불일치가 났을 때 원인이 정규화 규칙 탓인지 실제 값 차이인지
    구분하려면 정규화 전 값과 출처 위치가 함께 남아 있어야 한다.
    """

    raw: str
    value: str
    loc: tuple[float, float] | str | None = None

    def loc_str(self) -> str:
        """도면이면 좌표, 엑셀이면 셀 주소를 사람이 읽을 형태로."""
        if self.loc is None:
            return ""
        if isinstance(self.loc, str):
            return self.loc
        return f"({self.loc[0]:.1f}, {self.loc[1]:.1f})"


@dataclass
class DeckRecord:
    """일람표 한 행. 도면과 엑셀이 같은 형태를 만든다."""

    symbol: str
    fields: dict[str, Cell] = field(default_factory=dict)
    source: str = ""
