# emit 스크립트 입력/출력 경로 설정 파일화 — 설계

날짜: 2026-08-29
대상: `convert-dxf-to-excel/`의 `emit_areas.py`, `emit_by_zone.py`, `emit_order.py`, `emit_sheet1.py`

## 배경 / 문제

4개 emit 스크립트가 입력·출력 경로를 여러 곳에 하드코딩하고 있다.

- 입력 경로가 두 갈래로 흩어져 있음:
  - 공유 모듈 상수: `poc_deckorder.SHOP_DXF`, `poc_deckorder.DETAIL_DXF`, `poc_deckorder.EXCEL_GLOB`
  - 일부 스크립트의 로컬 상수: `emit_by_zone.py`의 `DETAIL_DXF = "output/260610_...DECK DETAIL.dxf"`, `EXCEL_GLOB = "excel/*.xlsm"`
- 출력 경로가 각 스크립트에 하드코딩: `OUT_DIR = "golden/발주서"`, `OUT_DIR = "golden/구역별"`
- 스크립트가 참조하는 `output/`, `excel/` 디렉토리는 실제로 존재하지 않는다. 원본 데이터는 `arch-docs/dxf/`, `arch-docs/excel/`에 있다.

경로를 바꾸려면 여러 파일을 손대야 하고, 입력 소스가 실제 파일 위치와 어긋나 있다.

## 목표

입력·출력 경로를 **하나의 설정 파일(`config.yaml`)**에서 관리한다. 경로를 바꿀 때 이 파일만 수정하면 되도록 한다.

## 비범위 (YAGNI)

- 여러 프로젝트 프로파일 지원
- CLI 인자로 경로 오버라이드
- 설정 스키마 검증 라이브러리
- 누락된 `poc_deckorder.py` / `deckcheck/` 모듈 복원 (이번 작업과 별개. 아래 "알려진 제약" 참조)

## 설계

### 1. `config.yaml` (작업 폴더 루트 `convert-dxf-to-excel/`)

입력·출력 경로의 단일 소스.

```yaml
input:
  shop_dxf:   "arch-docs/dxf/260601_식사푸르지오_DECK SHOP_B1F ,1F 발주 구간(0529 수취 반영도면).dxf"
  detail_dxf: "arch-docs/dxf/260610_식사푸르지오_DECK DETAIL.dxf"
  excel_glob: "arch-docs/excel/*.xlsm"
output:
  areas_dir:   "golden/발주서"    # emit_areas.py
  by_zone_dir: "golden/구역별"    # emit_by_zone.py / emit_order.py / emit_sheet1.py
```

- 경로는 `config.yaml`이 있는 디렉토리를 기준으로 해석한다(상대경로 안정성).

### 2. `deckconfig.py` (로더 모듈)

- `config.yaml`을 **모듈 파일 위치 기준**으로 찾아 로드한다. 현재 작업 디렉토리(cwd)에 흔들리지 않게 한다.
- 환경변수 `DECK_CONFIG`가 있으면 그 경로의 설정 파일을 대신 로드한다.
- 상대경로 값은 설정 파일이 있는 디렉토리 기준 절대경로로 변환해 노출한다.
- 접근 인터페이스 (속성):
  - `cfg.shop_dxf`
  - `cfg.detail_dxf`
  - `cfg.excel_glob`
  - `cfg.areas_dir`
  - `cfg.by_zone_dir`
- 로드는 모듈에서 1회 수행하고 캐시한다.

### 3. emit 스크립트 4종 수정

호출부의 경로 상수만 config 참조로 교체한다. `poc_deckorder`의 함수 시그니처는 건드리지 않는다(경로를 인자로 받는 구조라 호출부 교체만으로 충분).

- `emit_areas.py`
  - `M.SHOP_DXF` → `cfg.shop_dxf`, `M.DETAIL_DXF` → `cfg.detail_dxf`, `M.EXCEL_GLOB` → `cfg.excel_glob`
  - `OUT_DIR = "golden/발주서"` → `cfg.areas_dir`
- `emit_by_zone.py`
  - 로컬 `DETAIL_DXF`, `EXCEL_GLOB` 상수 제거 → `cfg.detail_dxf`, `cfg.excel_glob`
  - `OUT_DIR = "golden/구역별"` → `cfg.by_zone_dir`
- `emit_order.py`
  - `M.SHOP_DXF`, `M.DETAIL_DXF`, `M.EXCEL_GLOB` → `cfg.*`
  - `OUT_DIR = "golden/구역별"` → `cfg.by_zone_dir`
- `emit_sheet1.py`
  - `M.SHOP_DXF` → `cfg.shop_dxf`
  - `OUT_DIR = "golden/구역별"` → `cfg.by_zone_dir`

### 4. `requirements.txt`

- `PyYAML` (신규 의존성), `openpyxl` 명시. PyYAML 설치.

## 데이터 흐름

```
config.yaml ──load──▶ deckconfig.py (cfg) ──▶ emit_*.py ──▶ poc_deckorder / deckcheck 함수에 경로 인자로 전달
```

## 에러 처리

- `config.yaml` 없음 / `DECK_CONFIG`가 가리키는 파일 없음: `FileNotFoundError`에 어떤 경로를 찾았는지 담아 즉시 실패.
- 필수 키 누락(`input.shop_dxf` 등): `KeyError`에 누락 키 이름을 담아 즉시 실패.

## 테스트 / 검증

- `deckconfig.py` 단독: 임의 cwd에서 import해도 경로가 설정 파일 기준으로 올바르게 해석되는지 확인. `DECK_CONFIG` 오버라이드 동작 확인.
- emit 스크립트: 각 파일이 `deckconfig`를 import하고 하드코딩 경로 상수가 모두 제거됐는지 확인(`grep`). `python -c "import ast"` 컴파일 통과 확인.

## 알려진 제약

`poc_deckorder.py`와 `deckcheck/` 패키지가 저장소에 없어 emit 스크립트를 **끝까지 실행**하는 end-to-end 검증은 현재 불가능하다. 이 작업은 경로 배선 리팩터링이므로, 로더 단독 동작과 스크립트의 import/컴파일 및 경로 상수 제거로 검증한다. 모듈이 확보되면 실제 실행 검증을 추가한다.
