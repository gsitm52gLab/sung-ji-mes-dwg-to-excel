# emit 스크립트 입력/출력 경로 설정 파일화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 4개 emit 스크립트의 입력·출력 경로를 단일 `config.yaml`에서 읽도록 리팩터링한다.

**Architecture:** `config.yaml`(YAML)에 입력(dxf/excel glob)·출력(golden 디렉토리) 경로를 담고, `deckconfig.py` 로더가 이를 읽어 `cfg` 객체로 노출한다. 각 emit 스크립트는 하드코딩된 경로 상수(`M.SHOP_DXF`, 로컬 `OUT_DIR` 등)를 `cfg.*` 참조로 교체한다. `poc_deckorder`/`deckcheck` 함수 시그니처는 건드리지 않는다.

**Tech Stack:** Python 3.14, PyYAML, openpyxl.

## Global Constraints

- 작업 디렉토리: `convert-dxf-to-excel/` (모든 상대경로의 기준).
- `config.yaml`은 `convert-dxf-to-excel/` 루트에 둔다. 경로 값은 `config.yaml` 위치 기준으로 해석한다.
- `arch-docs/`는 `convert-dxf-to-excel/`의 상위에 있으므로 입력 경로는 `../arch-docs/...`로 시작한다.
- 로더 접근 인터페이스(고정): `cfg.shop_dxf`, `cfg.detail_dxf`, `cfg.excel_glob`, `cfg.areas_dir`, `cfg.by_zone_dir` — 모두 절대경로 문자열.
- 환경변수 `DECK_CONFIG`가 있으면 그 경로의 설정 파일을 로드한다.
- `poc_deckorder.py` / `deckcheck/`가 저장소에 없어 emit 스크립트의 **런타임 import·실행은 불가**. 검증은 `python3 -m py_compile`(import 실행 안 함)과 `grep`으로 한다.

---

### Task 1: 설정 로더 + config.yaml + 의존성

`deckconfig.py` 로더, `config.yaml`, `requirements.txt`를 만들고 PyYAML을 설치한다. 로더는 설정 파일 위치 기준으로 경로를 절대경로로 변환해 노출하고 `DECK_CONFIG` 오버라이드를 지원한다.

**Files:**
- Create: `convert-dxf-to-excel/deckconfig.py`
- Create: `convert-dxf-to-excel/config.yaml`
- Create: `convert-dxf-to-excel/requirements.txt`
- Create: `convert-dxf-to-excel/test_deckconfig.py`

**Interfaces:**
- Consumes: 없음.
- Produces: `deckconfig` 모듈의 `cfg` 객체 (속성: `shop_dxf`, `detail_dxf`, `excel_glob`, `areas_dir`, `by_zone_dir` — 절대경로 `str`). 로더 함수 `load(path)` → `_Config`.

- [ ] **Step 1: PyYAML 설치 및 requirements.txt 작성**

`convert-dxf-to-excel/requirements.txt` 생성:

```
PyYAML>=6.0
openpyxl>=3.1
```

설치:

Run: `python3 -m pip install -r requirements.txt`
Expected: PyYAML, openpyxl 설치 완료 (openpyxl은 이미 있을 수 있음).

확인:

Run: `python3 -c "import yaml; print(yaml.__version__)"`
Expected: 버전 문자열 출력 (예: `6.0.2`).

- [ ] **Step 2: 실패하는 테스트 작성**

`convert-dxf-to-excel/test_deckconfig.py` 생성. pytest 없이 `python3`로 직접 실행 가능하게 plain assert + `main()` 구조로 작성한다. 임시 config를 `DECK_CONFIG`로 지정해 경로 해석과 오버라이드를 검증한다.

```python
#!/usr/bin/env python3
"""deckconfig 로더 테스트. pytest 불필요: `python3 test_deckconfig.py`."""

import os
import tempfile
from pathlib import Path


def test_resolves_paths_relative_to_config_file():
    """경로는 cwd가 아니라 config.yaml 위치 기준으로 절대경로가 된다."""
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "config.yaml"
        cfg_path.write_text(
            "input:\n"
            "  shop_dxf: sub/shop.dxf\n"
            "  detail_dxf: sub/detail.dxf\n"
            "  excel_glob: xl/*.xlsm\n"
            "output:\n"
            "  areas_dir: out/areas\n"
            "  by_zone_dir: out/zone\n",
            encoding="utf-8",
        )
        import deckconfig
        cfg = deckconfig.load(cfg_path)
        assert cfg.shop_dxf == str(Path(d) / "sub/shop.dxf"), cfg.shop_dxf
        assert cfg.detail_dxf == str(Path(d) / "sub/detail.dxf"), cfg.detail_dxf
        assert cfg.excel_glob == str(Path(d) / "xl/*.xlsm"), cfg.excel_glob
        assert cfg.areas_dir == str(Path(d) / "out/areas"), cfg.areas_dir
        assert cfg.by_zone_dir == str(Path(d) / "out/zone"), cfg.by_zone_dir


def test_env_override():
    """DECK_CONFIG가 기본 config.yaml 대신 로드된다."""
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "custom.yaml"
        cfg_path.write_text(
            "input:\n  shop_dxf: a.dxf\n  detail_dxf: b.dxf\n  excel_glob: c/*.xlsm\n"
            "output:\n  areas_dir: x\n  by_zone_dir: y\n",
            encoding="utf-8",
        )
        os.environ["DECK_CONFIG"] = str(cfg_path)
        try:
            import deckconfig
            cfg = deckconfig.load(deckconfig.find_config_path())
            assert cfg.shop_dxf == str(Path(d) / "a.dxf"), cfg.shop_dxf
        finally:
            del os.environ["DECK_CONFIG"]


def test_missing_key_raises():
    """필수 키 누락 시 KeyError."""
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "config.yaml"
        cfg_path.write_text("input:\n  shop_dxf: a.dxf\n", encoding="utf-8")
        import deckconfig
        try:
            deckconfig.load(cfg_path)
        except KeyError:
            return
        raise AssertionError("KeyError가 발생해야 한다")


def main():
    test_resolves_paths_relative_to_config_file()
    test_env_override()
    test_missing_key_raises()
    print("OK: 3개 테스트 통과")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python3 test_deckconfig.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'deckconfig'`.

- [ ] **Step 4: deckconfig.py 구현**

`convert-dxf-to-excel/deckconfig.py` 생성:

```python
#!/usr/bin/env python3
"""입력/출력 경로 설정 로더.

config.yaml(기본: 이 모듈과 같은 디렉토리)을 읽어 경로를 절대경로로 노출한다.
경로는 설정 파일 위치 기준으로 해석하므로 실행 cwd에 흔들리지 않는다.
환경변수 DECK_CONFIG로 다른 설정 파일을 지정할 수 있다.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

_MODULE_DIR = Path(__file__).resolve().parent


class _Config:
    def __init__(self, path):
        self.path = Path(path).resolve()
        with open(self.path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        base = self.path.parent

        def resolve(section, key):
            try:
                value = data[section][key]
            except (KeyError, TypeError):
                raise KeyError(f"{self.path}에 필수 키가 없습니다: {section}.{key}")
            return str((base / value).resolve() if not os.path.isabs(value)
                       else Path(value))

        self.shop_dxf = resolve("input", "shop_dxf")
        self.detail_dxf = resolve("input", "detail_dxf")
        self.excel_glob = resolve("input", "excel_glob")
        self.areas_dir = resolve("output", "areas_dir")
        self.by_zone_dir = resolve("output", "by_zone_dir")


def find_config_path():
    """DECK_CONFIG > 모듈 디렉토리의 config.yaml 순으로 설정 파일을 찾는다."""
    env = os.environ.get("DECK_CONFIG")
    if env:
        p = Path(env)
        if not p.exists():
            raise FileNotFoundError(f"DECK_CONFIG가 가리키는 설정 파일이 없습니다: {p}")
        return p
    p = _MODULE_DIR / "config.yaml"
    if not p.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {p}")
    return p


def load(path):
    return _Config(path)


cfg = load(find_config_path())
```

주의: `resolve()`의 절대경로 분기는 `Path(base / value)`에 `.resolve()`를 쓰는데, glob 패턴(`*.xlsm`)도 `.resolve()`가 심볼릭 정규화만 하고 와일드카드는 보존하므로 안전하다. 단 테스트는 `str(Path(d) / "xl/*.xlsm")`와 정확히 비교하므로, 심볼릭 링크 없는 임시 디렉토리에서 `.resolve()` 결과가 동일해야 한다. macOS `/var`→`/private/var` 정규화 문제를 피하려면 비교도 동일 기준이어야 한다 — 아래 Step 5에서 이를 반영해 테스트를 `os.path.realpath` 기준으로 맞춘다.

- [ ] **Step 5: 테스트를 realpath 기준으로 맞추고 재확인**

macOS의 `TemporaryDirectory`는 `/var/...`(심볼릭)이고 `.resolve()`는 `/private/var/...`로 정규화한다. 비교 양변을 `os.path.realpath`로 통일한다. `test_deckconfig.py`의 각 기대값을 `os.path.realpath(...)`로 감싼다:

```python
# test_resolves_paths_relative_to_config_file 내부, 예:
import os
base = os.path.realpath(d)
assert cfg.shop_dxf == os.path.realpath(str(Path(base) / "sub/shop.dxf")), cfg.shop_dxf
assert cfg.detail_dxf == os.path.realpath(str(Path(base) / "sub/detail.dxf")), cfg.detail_dxf
assert cfg.excel_glob == os.path.realpath(str(Path(base) / "xl/*.xlsm")), cfg.excel_glob
assert cfg.areas_dir == os.path.realpath(str(Path(base) / "out/areas")), cfg.areas_dir
assert cfg.by_zone_dir == os.path.realpath(str(Path(base) / "out/zone")), cfg.by_zone_dir
```

`test_env_override`도 동일하게:

```python
assert cfg.shop_dxf == os.path.realpath(str(Path(d) / "a.dxf")), cfg.shop_dxf
```

Run: `python3 test_deckconfig.py`
Expected: `OK: 3개 테스트 통과`

- [ ] **Step 6: config.yaml 작성**

`convert-dxf-to-excel/config.yaml` 생성:

```yaml
# emit 스크립트 입력/출력 경로. 경로는 이 파일 위치(convert-dxf-to-excel/) 기준.
# arch-docs/ 는 상위 디렉토리에 있으므로 ../ 로 시작한다.
input:
  shop_dxf:   "../arch-docs/dxf/260601_식사푸르지오_DECK SHOP_B1F ,1F 발주 구간(0529 수취 반영도면).dxf"
  detail_dxf: "../arch-docs/dxf/260610_식사푸르지오_DECK DETAIL.dxf"
  excel_glob: "../arch-docs/excel/*.xlsm"
output:
  areas_dir:   "golden/발주서"    # emit_areas.py
  by_zone_dir: "golden/구역별"    # emit_by_zone.py / emit_order.py / emit_sheet1.py
```

- [ ] **Step 7: config.yaml 실경로 로드 확인**

Run: `python3 -c "from deckconfig import cfg; import os; print('shop', os.path.exists(cfg.shop_dxf)); print('detail', os.path.exists(cfg.detail_dxf)); print('areas_dir', cfg.areas_dir); print('by_zone_dir', cfg.by_zone_dir)"`
Expected: `shop True`, `detail True` (입력 파일 실제 존재), `areas_dir`/`by_zone_dir` 절대경로 출력.

- [ ] **Step 8: 커밋**

```bash
git add convert-dxf-to-excel/deckconfig.py convert-dxf-to-excel/config.yaml convert-dxf-to-excel/requirements.txt convert-dxf-to-excel/test_deckconfig.py
git commit -m "feat: config.yaml 기반 경로 로더(deckconfig) 추가"
```

---

### Task 2: emit 스크립트 4종을 config 참조로 배선

각 스크립트의 하드코딩 경로 상수를 `deckconfig.cfg` 참조로 교체한다. import 문에 `from deckconfig import cfg`를 추가하고, `M.SHOP_DXF`/`M.DETAIL_DXF`/`M.EXCEL_GLOB`, 로컬 `OUT_DIR`/`DETAIL_DXF`/`EXCEL_GLOB`를 대응하는 `cfg.*`로 바꾼다.

**Files:**
- Modify: `convert-dxf-to-excel/emit_areas.py`
- Modify: `convert-dxf-to-excel/emit_by_zone.py`
- Modify: `convert-dxf-to-excel/emit_order.py`
- Modify: `convert-dxf-to-excel/emit_sheet1.py`

**Interfaces:**
- Consumes: `deckconfig.cfg` (Task 1) — 속성 `shop_dxf`, `detail_dxf`, `excel_glob`, `areas_dir`, `by_zone_dir`.
- Produces: 없음 (스크립트 최종 산출물은 기존과 동일).

- [ ] **Step 1: emit_areas.py 수정**

import 블록(라인 26~28 부근)에 로더 추가. `import poc_deckorder as M` 다음 줄에:

```python
from deckconfig import cfg
```

`OUT_DIR = "golden/발주서"` (라인 30) 삭제.

`main()` 내부 교체:
- 라인 142 `os.makedirs(OUT_DIR, exist_ok=True)` → `os.makedirs(cfg.areas_dir, exist_ok=True)`
- 라인 143 `M.extract_shop(M.SHOP_DXF)` → `M.extract_shop(cfg.shop_dxf)`
- 라인 144 `M.load_type_master(M.DETAIL_DXF)` → `M.load_type_master(cfg.detail_dxf)`
- 라인 148 `M.load_oracle(M.EXCEL_GLOB)` → `M.load_oracle(cfg.excel_glob)`
- 라인 161 `os.path.join(OUT_DIR, f"B1F-{area}.xlsx")` → `os.path.join(cfg.areas_dir, f"B1F-{area}.xlsx")`
- 라인 179 `print(f"→ {OUT_DIR}/ ...` → `print(f"→ {cfg.areas_dir}/ ...` (나머지 문자열 유지)

`existing_orders()`의 라인 131 `glob.glob(M.EXCEL_GLOB)` → `glob.glob(cfg.excel_glob)`.

- [ ] **Step 2: emit_by_zone.py 수정**

import 블록에 추가 (라인 22 `from deckcheck.report import write_csv` 다음):

```python
from deckconfig import cfg
```

로컬 상수 삭제 (라인 24~26):

```python
DETAIL_DXF = "output/260610_식사푸르지오_DECK DETAIL.dxf"
EXCEL_GLOB = "excel/*.xlsm"
OUT_DIR = "golden/구역별"
```

교체:
- 라인 58 `os.makedirs(OUT_DIR, exist_ok=True)` → `os.makedirs(cfg.by_zone_dir, exist_ok=True)`
- 라인 60 `load_all(DETAIL_DXF)` → `load_all(cfg.detail_dxf)`
- 라인 64 `glob.glob(EXCEL_GLOB)` → `glob.glob(cfg.excel_glob)`
- 라인 72 `os.path.join(OUT_DIR, f"일람표_{zone}.xlsx")` → `os.path.join(cfg.by_zone_dir, f"일람표_{zone}.xlsx")`
- 라인 94 `os.path.join(OUT_DIR, "구역별_대조.csv")` → `os.path.join(cfg.by_zone_dir, "구역별_대조.csv")`

- [ ] **Step 3: emit_order.py 수정**

import 블록에 추가 (라인 19 `from emit_sheet1 import ...` 다음):

```python
from deckconfig import cfg
```

`OUT_DIR = "golden/구역별"` (라인 21) 삭제.

교체:
- 라인 130 `os.makedirs(OUT_DIR, exist_ok=True)` → `os.makedirs(cfg.by_zone_dir, exist_ok=True)`
- 라인 131 `M.extract_shop(M.SHOP_DXF)` → `M.extract_shop(cfg.shop_dxf)`
- 라인 133 `M.load_type_master(M.DETAIL_DXF)` → `M.load_type_master(cfg.detail_dxf)`
- 라인 134 `M.load_oracle(M.EXCEL_GLOB)` → `M.load_oracle(cfg.excel_glob)`
- 라인 136 `glob.glob(M.EXCEL_GLOB)` → `glob.glob(cfg.excel_glob)`
- 라인 145 `os.path.join(OUT_DIR, f"제작의뢰서_{zone}.xlsx")` → `os.path.join(cfg.by_zone_dir, f"제작의뢰서_{zone}.xlsx")`

- [ ] **Step 4: emit_sheet1.py 수정**

import 블록에 추가 (라인 21 `import poc_deckorder as M` 다음):

```python
from deckconfig import cfg
```

`OUT_DIR = "golden/구역별"` (라인 23) 삭제.

교체:
- 라인 105 `os.makedirs(OUT_DIR, exist_ok=True)` → `os.makedirs(cfg.by_zone_dir, exist_ok=True)`
- 라인 106 `M.extract_shop(M.SHOP_DXF)` → `M.extract_shop(cfg.shop_dxf)`
- 라인 111 `glob.glob(M.EXCEL_GLOB)` → `glob.glob(cfg.excel_glob)`
- 라인 120 `os.path.join(OUT_DIR, f"Sheet1_{zone}.xlsx")` → `os.path.join(cfg.by_zone_dir, f"Sheet1_{zone}.xlsx")`

- [ ] **Step 5: 하드코딩 경로 상수 잔존 여부 확인**

Run: `grep -nE 'OUT_DIR|M\.SHOP_DXF|M\.DETAIL_DXF|M\.EXCEL_DXF|M\.EXCEL_GLOB|"golden/|"output/|"excel/' emit_areas.py emit_by_zone.py emit_order.py emit_sheet1.py`
Expected: 출력 없음 (매치 0건). `grep` 종료코드 1이 정상.

Run: `grep -nc 'from deckconfig import cfg' emit_areas.py emit_by_zone.py emit_order.py emit_sheet1.py`
Expected: 각 파일 `1`.

- [ ] **Step 6: 컴파일 확인**

`poc_deckorder`/`deckcheck` 부재로 실행/import는 불가하므로 문법·바이트코드 컴파일로 검증한다 (py_compile은 import를 실행하지 않는다).

Run: `python3 -m py_compile emit_areas.py emit_by_zone.py emit_order.py emit_sheet1.py deckconfig.py && echo COMPILE_OK`
Expected: `COMPILE_OK`

- [ ] **Step 7: 커밋**

```bash
git add convert-dxf-to-excel/emit_areas.py convert-dxf-to-excel/emit_by_zone.py convert-dxf-to-excel/emit_order.py convert-dxf-to-excel/emit_sheet1.py
git commit -m "refactor: emit 스크립트 경로를 config.yaml에서 읽도록 배선"
```

---

## 검증 요약

- 로더 단독: `python3 test_deckconfig.py` → 3개 통과.
- 실경로 로드: `from deckconfig import cfg`로 입력 파일 존재 확인.
- 배선: `grep`으로 하드코딩 상수 0건 + `from deckconfig import cfg` 각 1건, `py_compile` 통과.
- (제약) `poc_deckorder`/`deckcheck` 확보 후 end-to-end 실행 검증은 별도 후속 작업.

## Self-Review 메모

- 스펙 커버리지: config.yaml(있음), deckconfig 로더(Task1), 4스크립트 배선(Task2), requirements(Task1), 에러 처리(로더 KeyError/FileNotFoundError, Task1 Step4·테스트), 알려진 제약(py_compile 검증) — 전부 태스크에 매핑됨.
- 타입 일관성: 로더 속성명 `shop_dxf/detail_dxf/excel_glob/areas_dir/by_zone_dir`이 Task1 정의와 Task2 사용에서 동일.
- 플레이스홀더: 없음.
