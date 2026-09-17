# 도면 검증 채팅 UI + Gemini 연동 설계

작성일: 2026-09-17

## 배경

`frontend/index.html` 은 2400×1200 고정 크기의 정적 렌더링 목업이다. 대화 내용이
HTML 에 하드코딩되어 있고 입력창은 `readonly` 더미다. 발표 시안에 가깝다.

목업이 그리는 흐름(도면 접수 → AI 추출 → 불일치 대조 → 발주 확정)은 이 리포지토리의
Python 파이프라인과 정확히 대응한다. 이 목업을 실제로 동작하는 채팅 UI로 만들고,
대조 결과를 근거로 질의응답하는 LLM 을 붙인다.

## 목표와 비목표

### 목표
- 목업의 레이아웃·색·아이콘을 유지한 채 실제 브라우저에서 동작하는 반응형 채팅 UI
- 사용자 질문에 Gemini 가 **기존 대조 결과를 근거로** 답변, 응답은 스트리밍
- Hugging Face Spaces(Private)에 배포해 사내 인원이 접속

### 비목표 (이번 범위 밖)
- dwg 업로드 및 변환 파이프라인 실행
- 구역 선택 UI, 예외 승인 기록(Decision Traceability), 잔디 송부
- 대화 이력 서버 영속화

위 기능의 UI 요소는 목업 그대로 두되 `disabled` 처리하고 "데모" 배지를 붙인다.

## 스택 결정

**FastAPI + 정적 프런트, Hugging Face Spaces(Docker SDK) 배포.**

검토한 대안과 탈락 이유:

| 안 | 탈락 이유 |
|---|---|
| Next.js + Vercel | 서버리스라 Python CLI `spawn` 불가, 파일시스템 읽기 전용. 파이프라인 연동이 영구히 막힌다 |
| Streamlit + Community Cloud | 구현·배포는 가장 빠르나 목업 디자인을 버려야 한다 |
| 브라우저에서 Gemini 직접 호출 | API 키가 클라이언트에 노출되고 로컬 데이터를 읽을 수 없다 |

FastAPI 를 고른 이유는 단일 언어 유지, 목업 디자인 보존, 그리고 HF Spaces 가 일반
Docker 컨테이너라서 나중에 `convert-dwg-to-dxf/Dockerfile`(ODAFileConverter)까지
합칠 길이 열려 있다는 점이다.

## 배포 구조

HF Space 는 자체 git 리포지토리다. `frontend/` 를 Space 루트로 삼아
`git subtree push --prefix=frontend hf main` 으로 올린다.

이 방식에서는 리포 루트의 `config.yaml` 과 `convert-dxf-to-excel/output/` 이
따라가지 않는다. 따라서 **배포용 데이터 스냅샷**을 `frontend/data/` 에 두고,
서버는 로컬이든 배포든 **항상 `frontend/data/` 만** 읽는다. 경로 분기가 없으므로
"로컬에선 되는데 배포하면 안 된다"가 구조적으로 발생하지 않는다.

`.gitignore` 의 `convert-dxf-to-excel/output/` 규칙은 그대로 둔다. 원본 산출물은
계속 제외하고, 스냅샷만 별도 경로에서 추적한다.

## 파일 구성

```
frontend/                      ← HF Space 루트
  README.md          HF front matter (sdk: docker, app_port: 7860)
  Dockerfile         python:3.12-slim + uvicorn
  requirements.txt   fastapi, uvicorn[standard], google-genai
  server.py          정적 서빙 + POST /api/chat (SSE) + 비밀번호 게이트
  context.py         대조 CSV → 시스템 프롬프트 문자열
  refresh_data.py    config.yaml 을 읽어 최신 대조 CSV 를 data/ 로 복사
  data/
    구역별_대조.csv   배포용 스냅샷 (git 추적)
  index.html
  styles.css
  app.js
  test_context.py
  test_server.py
```

각 모듈의 책임:

- **`context.py`** — CSV 경로를 받아 시스템 프롬프트 문자열을 반환한다. 순수 함수이며
  네트워크·FastAPI 에 의존하지 않는다. 단독으로 테스트된다.
- **`server.py`** — HTTP 경계. 컨텍스트 빌드는 `context.py` 에, LLM 호출은 주입된
  클라이언트에 위임한다. Gemini 클라이언트는 페이크로 바꿔 끼울 수 있어야 한다.
- **`refresh_data.py`** — 개발자가 수동으로 돌리는 스냅샷 갱신 도구. 서버는 이것을
  임포트하지 않는다.
- **`app.js`** — 채팅 상태와 DOM 렌더. 서버 응답 형식(SSE 프레임)만 알면 된다.

## 데이터 흐름

1. 서버 기동 시 `context.py` 가 `frontend/data/구역별_대조.csv` 를 읽어 시스템
   프롬프트를 만들고 메모리에 캐시한다. 요청마다 다시 만들지 않는다.
2. 브라우저가 `POST /api/chat` 에 `{"messages": [{"role": ..., "content": ...}, ...]}`
   를 보낸다.
3. 서버가 시스템 프롬프트 + 대화 이력으로 Gemini 스트리밍 호출을 하고, 받은 토큰을
   SSE 로 흘린다.
4. `app.js` 가 토큰을 받아 `.bubble-ai` 에 점진 렌더하고 자동 스크롤한다.

대화 이력은 클라이언트 메모리에만 존재한다. 새로고침하면 초기화된다. 서버는 무상태다.

### SSE 프레임 형식

```
event: token
data: {"text": "..."}

event: done
data: {}

event: error
data: {"message": "..."}
```

## 컨텍스트 빌드 규칙

대조 CSV 는 421행이며 컬럼은
`파일, 기호, 컬럼, 엑셀값, 엑셀셀, 도면원문, 도면정규화, 도면좌표, 판정` 이다.
판정값은 `일치`, `불일치`, `N/A`, `도면에 없음` 이다.

전체를 그대로 주입하지 않는다. 대부분이 `일치` 행이라 토큰만 소모하고 모델이
핵심(불일치)을 놓치게 만든다. 다음 세 부분으로 압축한다.

1. **구역별 집계** — 파일(=구역)마다 고유 기호 수, 비교 셀 수, 판정별 건수
2. **불일치·도면에 없음 행 전체 상세** — 기호, 컬럼, 엑셀값, 엑셀셀, 도면원문,
   도면정규화, 도면좌표까지 그대로. 이것이 대화의 실제 대상이다
3. **일치 행 요약** — 기호별로 어떤 컬럼이 일치했는지 한 줄 요약. 상세값은 생략

시스템 프롬프트에는 위 데이터와 함께, **주어진 데이터에 없는 내용을 지어내지 말고
모르면 모른다고 답하라**는 지시를 포함한다.

## 인증

두 겹으로 막는다. 실제 고객(대우건설 식사푸르지오) 도면 데이터가 올라가기 때문이다.

- **Private Space** — HF 조직 멤버만 접근. 데이터가 애초에 외부로 나가지 않는다
- **앱 비밀번호** — 환경변수 `APP_PASSWORD`, 쿠키 세션. Space 를 나중에 Public 으로
  돌려도 안전하다. 미설정 시 서버는 기동에 실패한다

`GEMINI_API_KEY` 는 HF Space Secret 으로 주입한다. 코드와 리포지토리에 넣지 않는다.

## UI 변경

목업의 레이아웃·색·아이콘은 유지한다. 바꾸는 것만 적는다.

- `html, body` 의 `width: 2400px; height: 1200px` → `100vw / 100dvh`.
  `.card` 의 고정 크기도 제거하고 남는 공간을 채우게 한다
- 우측 사이드바 `width: 500px` → `320px`
- `.chat` 에 `overflow-y: auto` + 새 메시지 도착 시 자동 스크롤
- 하드코딩된 대화 블록 전부 제거. 초기 화면에는 로드된 도면과 대조 요약을 알리는
  시스템 알림만 표시한다
- 입력창 `readonly` 해제. Enter 전송, Shift+Enter 줄바꿈, 전송 중 비활성
- 인라인 `<style>` 을 `styles.css` 로 분리
- 우측 진행상황 스텝, 도면 업로드 카드, 잔디 송부 버튼은 시안 그대로 두되
  `disabled` 처리하고 "데모" 배지를 붙인다

### 로그인 화면

세션 쿠키가 없으면 채팅 대신 로그인 화면을 보여준다. 목업의 `.card` 골격과 색을
그대로 쓰고 안에 비밀번호 입력 한 칸과 버튼만 둔다. 인증에 성공하면 세션 쿠키를
받고 채팅 화면으로 전환한다. 실패하면 화면을 유지한 채 오류 문구를 띄운다.

## 에러 처리

| 상황 | 동작 |
|---|---|
| `GEMINI_API_KEY` 없음 | 기동 즉시 실패, 설정 방법 안내 메시지 |
| `APP_PASSWORD` 없음 | 기동 즉시 실패 |
| 대조 CSV 없음 | 컨텍스트 없이 기동. 채팅 상단에 "대조 결과 없음 — deckcheck 를 먼저 실행하세요" 시스템 알림 표시 |
| Gemini 호출 실패 | SSE `event: error` → 채팅에 오류 카드와 재시도 버튼 |
| 스트리밍 중 연결 끊김 | 받은 부분 응답은 유지하고 재시도 버튼 노출 |
| 비밀번호 불일치 | 401, 로그인 화면 유지 |

## 테스트

기존 `convert-dxf-to-excel/test_shopcache.py` 의 pytest 관례를 따른다.

- **`test_context.py`** — 소규모 CSV 픽스처를 만들어, 구역별 집계 건수가 맞는지,
  불일치·도면에 없음 행이 빠짐없이 상세에 들어가는지, 빈 CSV·파일 없음을 어떻게
  처리하는지 검증한다
- **`test_server.py`** — Gemini 클라이언트를 페이크로 주입해 `/api/chat` 이 내는
  SSE 프레임 형식을 검증한다. 정상 스트림, LLM 예외 발생, 인증 실패 세 경우를 다룬다.
  실제 Gemini API 는 호출하지 않는다

## 의존성

`frontend/requirements.txt` 를 새로 만든다. 리포 루트 `requirements.txt` 는 건드리지
않는다. 파이프라인과 웹앱의 의존성은 분리한다.

```
fastapi
uvicorn[standard]
google-genai
```

`context.py` 는 표준 라이브러리 `csv` 만 쓴다. `refresh_data.py` 만 `config.yaml`
파싱을 위해 PyYAML 이 필요한데, 이는 루트 `requirements.txt` 에 이미 있고 배포
컨테이너에서는 실행되지 않으므로 `frontend/requirements.txt` 에 넣지 않는다.

## 구현 시 확인이 필요한 사항

기억에 의존해 단정하지 않고 구현 시점에 실제로 확인한다.

- `google-genai` 의 정확한 스트리밍 API 형태와 사용할 모델 식별자
- HF Spaces 무료 등급 조건, Private Space 설정 방법, Secret 주입 방식
- HF Spaces Docker SDK 가 요구하는 `README.md` front matter 필드와 포트 규약
