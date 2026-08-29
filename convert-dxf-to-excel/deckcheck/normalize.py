"""값 정규화 규칙.

전부 순수 함수다. 도면과 엑셀이 같은 값을 다르게 적는 지점을 여기 한 곳에
모아둔다 — 이 프로그램에서 가장 자주 손대게 될 부분이라, 파싱 코드와
섞이면 금방 유지보수가 어려워진다.
"""

from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")
_CAMBER_PREFIX_RE = re.compile(r"^[A-Za-z]+/")


def norm_text(value: object) -> str:
    """어떤 값이든 비교 가능한 문자열로.

    엑셀은 숫자를 int/float로 돌려주고 도면은 문자열로 준다.
    150 과 150.0 과 '150' 이 같은 것으로 취급되어야 한다.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return _WS_RE.sub(" ", str(value)).strip()


def norm_lattice(value: object) -> str:
    """래티스 선경: 'ø5' → 'Ø5'.

    도면은 U+00F8(소문자 ø), 엑셀은 U+00D8(대문자 Ø)를 쓴다.
    유니코드 대문자화 규칙이 이미 이 변환을 하므로 별도 치환표를 두지 않는다.
    """
    return norm_text(value).upper()


def norm_camber(value: object) -> str:
    """캠버: 'LX/200' → '200', '-' → '-'.

    도면은 래티스 기호를 접두어로 붙여 적고 엑셀은 수치만 적는다.
    """
    return _CAMBER_PREFIX_RE.sub("", norm_text(value))


def split_code(value: object) -> tuple[str, str]:
    """표준코드를 엑셀의 TYPE / TG 두 컬럼으로 분해.

    'M13135-110' → ('M13135', '110'). 하이픈이 없으면 TG는 빈 문자열.
    """
    text = norm_text(value)
    head, sep, tail = text.partition("-")
    return (head, tail) if sep else (text, "")


def product_of(code: object) -> str:
    """표준코드 접두어로 제품 계열 판별.

    y좌표 범위를 상수로 박으면 도면 수정 한 번에 깨진다.
    접두어는 제품 규격이라 바뀌지 않는다.
    """
    text = norm_text(code).upper()
    if text.startswith("M"):
        return "MEGA"
    if text.startswith("T"):
        return "TERA"
    return "UNKNOWN"
