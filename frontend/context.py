"""대조 CSV 를 LLM 시스템 프롬프트로 바꾸는 모듈.

순수 함수만 둔다. 네트워크도 FastAPI 도 모른다.

입력은 파이프라인이 낸 `구역별_대조.csv` 다. 컬럼은
`파일, 기호, 컬럼, 엑셀값, 엑셀셀, 도면원문, 도면정규화, 도면좌표, 판정` 이고
판정값은 `일치`, `불일치`, `N/A`, `도면에 없음` 이다.

CSV 를 그대로 주입하지 않는다. 한 기호가 10행으로 흩어져 있어 모델이 읽기
어렵고, 좌표·셀주소처럼 질의응답에 쓰이지 않는 값이 절반을 차지한다.
기호를 한 줄로 모은 구역별 사양표로 재구성하고, 어긋난 셀은 그 자리에
표시하면서 별도 섹션에 상세를 따로 싣는다.
"""

from __future__ import annotations

import csv
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

MATCH = "일치"
MISMATCH = "불일치"
NOT_COMPARED = "N/A"
MISSING = "도면에 없음"

# 도면과 실제로 대조하는 컬럼. deckcheck.models.COMPARED_COLUMNS 와 같은 순서다.
SPEC_COLUMNS = (
    "TYPE",
    "THK.",
    "래티스",
    "캠버",
    "서포트",
    "TG",
    "상부피복",
    "하부피복",
)

# 판정이 어긋난 것으로 취급되는 값. 이 행들만 상세를 싣는다.
BAD_VERDICTS = (MISMATCH, MISSING)


@dataclass
class ZoneStats:
    """한 구역(엑셀 파일 하나)의 대조 집계."""

    name: str
    source_file: str
    symbols: "OrderedDict[str, dict[str, dict]]" = field(default_factory=OrderedDict)
    counts: "OrderedDict[str, int]" = field(default_factory=OrderedDict)

    @property
    def bad_cells(self) -> list[dict]:
        out = []
        for columns in self.symbols.values():
            for row in columns.values():
                if row["판정"] in BAD_VERDICTS:
                    out.append(row)
        return out


def zone_name(source_file: str) -> str:
    """엑셀 파일명에서 구역 이름을 뽑는다.

    파일명 형태가 두 가지다.
        0309-09~10-GHY_대우건설(현장명)_(MEGA)_B1F-C.xlsm
        0720-07_08-GHY_대우건설_현장명_MEGA_B1F-바_400.23(성지).xlsm

    둘 다 `층-구역` 토큰(B1F-C, B1F-바)을 포함한다. 언더스코어로 끊은 뒤
    하이픈을 낀 토큰 중 마지막 것을 구역으로 본다. 찾지 못하면 파일명을
    그대로 쓴다 — 이름을 지어내는 것보다 낫다.
    """
    stem = Path(source_file).stem
    for token in reversed(stem.split("_")):
        # 맨 앞 `0309-09~10-GHY` 같은 발주번호 토큰은 구역이 아니다.
        if "-" in token and not token[0].isdigit():
            return token
    return stem


def _read_rows(csv_path: Path) -> list[dict]:
    # 파이프라인이 BOM 을 붙여 내보내므로 utf-8-sig 로 읽는다.
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_zones(rows: list[dict]) -> "OrderedDict[str, ZoneStats]":
    """CSV 행을 구역 → 기호 → 컬럼 으로 접는다."""
    zones: OrderedDict[str, ZoneStats] = OrderedDict()
    for row in rows:
        source = row["파일"]
        name = zone_name(source)
        zone = zones.get(name)
        if zone is None:
            zone = zones[name] = ZoneStats(name=name, source_file=source)
        zone.symbols.setdefault(row["기호"], {})[row["컬럼"]] = row
        verdict = row["판정"]
        zone.counts[verdict] = zone.counts.get(verdict, 0) + 1
    return zones


def _cell_text(row: dict | None) -> str:
    """사양표 한 칸. 어긋난 셀은 값 대신 양쪽을 나란히 보여준다.

    값이 대시(`-`)인 것과 대조하지 못한 것(N/A)은 전혀 다른 뜻인데, 둘 다
    대시로 적으면 모델이 섞는다. 실제로 DS3S 의 캠버(`-`, 판정 일치)를
    "도면에 정보가 없어 대조하지 못함"으로 잘못 설명하는 것을 확인했다.
    그래서 대시는 `없음` 으로 풀어 쓰고, N/A 는 문장으로 못박는다.
    """
    if row is None:
        return "없음"
    verdict = row["판정"]
    value = (row["엑셀값"] or "").strip()
    if verdict == MATCH:
        return "없음" if value in ("", "-") else value
    if verdict == NOT_COMPARED:
        # 도면에 해당 정보 자체가 없는 컬럼. 엑셀값은 고정값 감시 대상이다.
        return f"대조불가(엑셀값 {value or '없음'})"
    if verdict == MISSING:
        return f"⚠엑셀={value or '없음'} / 도면에 기호 없음"
    return f"⚠엑셀={value or '없음'} ≠ 도면={(row['도면정규화'] or '').strip() or '없음'}"


def _render_zone(zone: ZoneStats) -> list[str]:
    lines = [f"### {zone.name}", f"원본 엑셀: {zone.source_file}"]
    counts = " / ".join(f"{k} {v}" for k, v in zone.counts.items())
    lines.append(f"판정 집계: {counts}")
    lines.append("")
    lines.append("| 기호 | " + " | ".join(SPEC_COLUMNS) + " |")
    lines.append("|" + "---|" * (len(SPEC_COLUMNS) + 1))
    for symbol, columns in zone.symbols.items():
        cells = [_cell_text(columns.get(c)) for c in SPEC_COLUMNS]
        lines.append(f"| {symbol} | " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def _render_bad_cells(zones: "OrderedDict[str, ZoneStats]") -> list[str]:
    """어긋난 셀 상세. 대화의 실제 대상이므로 원문·좌표까지 그대로 싣는다."""
    lines: list[str] = ["## 어긋난 셀 상세", ""]
    total = 0
    for zone in zones.values():
        bad = zone.bad_cells
        if not bad:
            continue
        total += len(bad)
        lines.append(f"### {zone.name}")
        for row in bad:
            lines.append(
                f"- 기호 {row['기호']} · 컬럼 {row['컬럼']} · 판정 {row['판정']}\n"
                f"  - 엑셀값 `{row['엑셀값']}` (셀 {row['엑셀셀']})\n"
                f"  - 도면원문 `{row['도면원문']}` → 정규화 `{row['도면정규화']}`"
                f" (좌표 {row['도면좌표']})"
            )
        lines.append("")
    if total == 0:
        lines.append(
            "어긋난 셀이 없다. 비교한 모든 셀이 도면과 엑셀에서 일치했다."
        )
        lines.append("")
    return lines


def render_data_section(rows: list[dict]) -> str:
    """대조 결과를 마크다운 한 덩어리로 만든다."""
    zones = build_zones(rows)
    totals: OrderedDict[str, int] = OrderedDict()
    for zone in zones.values():
        for verdict, n in zone.counts.items():
            totals[verdict] = totals.get(verdict, 0) + n

    na_columns: OrderedDict[str, int] = OrderedDict()
    for row in rows:
        if row["판정"] == NOT_COMPARED:
            na_columns[row["컬럼"]] = na_columns.get(row["컬럼"], 0) + 1

    symbol_count = len({r["기호"] for r in rows})
    lines = [
        "## 대조 요약",
        "",
        f"- 구역 {len(zones)}개, 기호 {symbol_count}종, 비교 셀 {len(rows)}건",
        "- 판정 집계: " + " / ".join(f"{k} {v}" for k, v in totals.items()),
    ]
    if na_columns:
        na_text = ", ".join(f"{k} {v}건" for k, v in na_columns.items())
        lines.append(
            f"- 비교 불가(N/A) 컬럼: {na_text}."
            " 도면에 해당 정보가 없어 대조하지 않고 고정값만 감시한다."
        )
    lines.append("")
    lines.append("## 구역별 사양표")
    lines.append("")
    lines.append("각 칸을 읽는 법:")
    lines.append(
        "- 보통 값(예: `200`, `사용`): 도면과 엑셀이 **대조되어 일치**한 값이다.\n"
        "- `없음`: 해당 항목이 **없다**는 뜻이다(캠버 없음, 서포트 미사용 등)."
        " 이것도 도면과 **대조되어 일치**한 결과다. 정보가 빠진 것이 아니다.\n"
        "- `대조불가(엑셀값 …)`: 도면에 이 항목 자체가 없어 **대조하지 못했다**."
        " 일치도 불일치도 아니다.\n"
        "- `⚠엑셀=… ≠ 도면=…`: 도면과 엑셀이 **어긋난** 칸이다."
    )
    lines.append("")
    for zone in zones.values():
        lines.extend(_render_zone(zone))
    lines.extend(_render_bad_cells(zones))
    return "\n".join(lines)


INSTRUCTIONS = """\
너는 데크 플레이트 발주 검증을 돕는 보조자다. 건축 도면(SHOP·DETAIL)에서 뽑은
부재 사양과, 사람이 만든 발주 엑셀의 `일람표` 시트를 셀 단위로 대조한 결과가
아래에 주어진다.

답변 규칙:
- 아래 데이터에 없는 내용은 절대 지어내지 마라. 모르면 "주어진 대조 결과에는
  없다"고 분명히 말하라.
- 수치나 기호를 언급할 때는 어느 구역의 어느 기호인지 함께 밝혀라.
- 판정이 `N/A` 인 것은 "일치"가 아니라 "도면에 정보가 없어 대조하지 못함"이다.
  이 둘을 섞지 마라.
- 한국어로, 현장 담당자가 읽을 만큼 간결하게 답하라. 불필요한 서론은 빼라.

용어:
- 기호(SLAB NAME): DS1, DS3S 처럼 도면에 쓰인 부재 코드
- TYPE: 데크 제품 코드, THK.: 슬래브 두께, 캠버: 솟음, TG: 데크 높이
- 서포트: 동바리 유무, 상부/하부피복: 피복 두께
"""

NO_DATA_INSTRUCTIONS = """\
너는 데크 플레이트 발주 검증을 돕는 보조자다. 그런데 지금 대조 결과 데이터가
서버에 없다.

사용자가 도면이나 발주서 내용을 물으면, 대조 결과가 아직 준비되지 않았으므로
답할 수 없다고 알리고, 파이프라인을 먼저 돌린 뒤 스냅샷을 갱신해야 한다고
안내하라. 절대로 값을 지어내지 마라. 한국어로 간결하게 답하라.
"""


def build_system_prompt(csv_path: str | Path | None) -> tuple[str, dict]:
    """시스템 프롬프트와 화면에 띄울 요약 메타를 돌려준다.

    CSV 가 없어도 예외를 던지지 않는다. 서버는 데이터 없이도 떠야 하고,
    그 사실을 사용자에게 알리는 것까지가 이 함수의 일이다.
    """
    path = Path(csv_path) if csv_path else None
    if path is None or not path.exists():
        return NO_DATA_INSTRUCTIONS, {"available": False, "source": str(path or "")}

    rows = _read_rows(path)
    if not rows:
        return NO_DATA_INSTRUCTIONS, {"available": False, "source": str(path)}

    zones = build_zones(rows)
    bad = sum(len(z.bad_cells) for z in zones.values())
    meta = {
        "available": True,
        "source": path.name,
        "zones": [z.name for z in zones.values()],
        "cell_count": len(rows),
        "match_count": sum(1 for r in rows if r["판정"] == MATCH),
        "bad_count": bad,
        "na_count": sum(1 for r in rows if r["판정"] == NOT_COMPARED),
    }
    return INSTRUCTIONS + "\n" + render_data_section(rows), meta
