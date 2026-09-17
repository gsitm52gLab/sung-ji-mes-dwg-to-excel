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
  static/
    styles.css
    app.js
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

구현 중 실제 데이터를 확인하면서 설계를 한 번 뒤집었다. 애초에는 "불일치 상세를
전부 싣고 일치 행은 요약"할 계획이었으나, **현재 데이터에는 불일치가 하나도 없다**
(420건 중 일치 336 / N/A 84 / 불일치 0). 그렇다면 대화의 실제 대상은 불일치가
아니라 기호별 사양 그 자체다. 그래서 다음처럼 재구성한다.

1. **대조 요약** — 구역 수, 기호 종수, 판정별 건수, N/A 컬럼과 그 이유
2. **구역별 사양표** — 한 기호를 한 줄로 모은 표. CSV 에서 기호 하나가 10행으로
   흩어져 있어 모델이 읽기 어렵고, 좌표·셀주소는 질의응답에 쓰이지 않는다.
   어긋난 칸은 그 자리에 `⚠엑셀=… ≠ 도면=…` 으로 표시한다
3. **어긋난 셀 상세** — 원문·정규화·좌표까지 그대로. 어긋난 셀이 없으면 없다고
   명시한다

불일치가 생기는 데이터가 들어와도 2·3 이 그대로 받아낸다.

결과적으로 56KB CSV 가 약 4,100자 프롬프트가 된다.

### 대시(`-`)와 N/A 를 구분해 표기한다

첫 구현에서는 값이 대시인 칸과 대조하지 못한 칸을 둘 다 `-` 로 렌더했다.
실제로 모델이 DS3S 의 캠버(`-`, 판정 **일치**)를 "도면에 정보가 없어 대조하지
못함"이라고 잘못 설명하는 것을 확인했다. 그래서 표기를 갈라놓았다.

| 칸 표기 | 뜻 |
|---|---|
| 보통 값 (`200`, `사용`) | 대조되어 일치한 값 |
| `없음` | 해당 항목이 없다는 뜻. 이것도 **대조되어 일치**한 결과다 |
| `대조불가(엑셀값 …)` | 도면에 항목 자체가 없어 대조하지 못함. 일치도 불일치도 아니다 |
| `⚠엑셀=… ≠ 도면=…` | 어긋난 칸 |

시스템 프롬프트에는 이 표기법 설명과 함께, **주어진 데이터에 없는 내용을 지어내지
말고 모르면 모른다고 답하라**는 지시를 포함한다.

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

## 검증

사용자 요청으로 자동화 테스트는 이번 범위에서 뺐다. 대신 서버를 실제로 띄워
다음을 눈으로 확인했다.

- 인증: 미인증 `/api/meta` → `authed:false`, 미인증 `/api/chat` → 401,
  틀린 비밀번호 → 401, 올바른 비밀번호 → 쿠키 발급 후 접근 가능
- 정적 서빙: `/`, `/static/styles.css`, `/static/app.js` 모두 200
- 스트리밍: 브라우저에서 SSE 토큰이 점진 렌더되고 마크다운 표가 그려진다
- 근거 있는 답변: "DS3S 와 DS3 의 차이" → 캠버·서포트 차이를 데이터대로 답함
- 환각 방지: "철근 배근간격" (데이터에 없는 항목) → "주어진 대조 결과에 없습니다"
- 다중 턴: "그 중 …" 이 앞 턴의 구역을 이어받음
- 에러 경로: `GEMINI_MODEL` 을 없는 모델로 띄워 SSE `event: error` 와 오류 카드,
  재시도 버튼 동작 확인
- 환경변수 가드: `APP_PASSWORD` 없이 임포트하면 `RuntimeError` 로 기동 실패

자동화 테스트가 없으므로, 이후 `context.py` 를 고칠 때는 서버를 띄워 위 항목을
다시 확인해야 한다.

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

## 확인한 사실 (구현 중 실측)

기억에 의존하지 않고 실제로 확인한 것들이다.

- **Gemini SDK**: `google-genai` 2.24.0. 호출은
  `client.models.generate_content_stream(model=…, contents=[types.Content(...)], config=…)`.
  시스템 프롬프트는 `GenerateContentConfig(system_instruction=…)` 로 넣는다.
  도구를 쓰지 않으므로 `automatic_function_calling(disable=True)` 로 경고를 껐다.
- **모델**: 기본값 `gemini-2.5-flash`. 실제로 스트리밍 응답을 받아 확인했다.
  `gemini-3.8-flash` 는 호출 시점에 503(수요 폭주)을 돌려줘 기본값으로 쓰지 않는다.
  `GEMINI_MODEL` 로 교체할 수 있다.
- **HF Spaces Docker SDK**: README front matter 는 `title, emoji, colorFrom,
  colorTo, sdk: docker, app_port`. 컨테이너는 **UID 1000** 으로 돌아가므로
  `useradd -m -u 1000 user` → `USER user` → `WORKDIR $HOME/app` 순서를 지키고
  모든 `COPY` 에 `--chown=user` 를 붙여야 한다. Secret 은 런타임 환경변수로
  주입된다. 디스크는 재시작 시 날아간다 — 무상태 설계와 맞는다.
- **아이콘 CDN**: 목업이 쓰던
  `tabler-icons/2.47.0/iconfont/tabler-icons.min.css` 는 **404** 였다.
  목업 시점부터 깨져 있었다. `tabler-icons/3.46.0/tabler-icons.min.css` 로
  교체했고 사용하는 아이콘 7종이 모두 들어 있는 것을 확인했다.

## 알려진 제약

- 자동화 테스트가 없다 (위 "검증" 참조)
- 한글 IME 로 입력할 때 Enter 는 조합을 확정하고, 한 번 더 눌러야 전송된다.
  `keydown` 의 `isComposing` 을 보고 있어 의도된 동작이다
- 대화 이력은 새로고침하면 사라진다
- 대조 데이터가 바뀌면 `refresh_data.py` 로 스냅샷을 갱신하고 커밋해야 한다
