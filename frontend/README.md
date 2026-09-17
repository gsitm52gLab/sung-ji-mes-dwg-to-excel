---
title: 데크 발주 검증 채팅
emoji: 📐
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# 데크 발주 검증 채팅

도면(SHOP·DETAIL)에서 뽑은 부재 사양과 발주 엑셀 `일람표` 시트를 셀 단위로
대조한 결과를 놓고 LLM 과 대화하는 화면이다.

LLM 은 **OpenAI 호환 엔드포인트면 무엇이든** 붙는다. NVIDIA NIM, Gemini 의
OpenAI 호환 경로, OpenAI 본체가 모두 같은 코드로 돌아간다. 공급자를 바꾸는 일은
코드 수정이 아니라 환경변수 두 개(`LLM_BASE_URL`, `LLM_MODEL`)를 고치는 일이다.

설계 문서: `docs/superpowers/specs/2026-09-17-frontend-chat-llm-design.md`

## 구성

| 파일 | 역할 |
|---|---|
| `server.py` | FastAPI — 정적 서빙, `/api/chat` SSE, 비밀번호 게이트 |
| `context.py` | 대조 CSV → 시스템 프롬프트 (순수 함수) |
| `refresh_data.py` | 파이프라인 산출물을 `data/` 스냅샷으로 복사 |
| `data/구역별_대조.csv` | 배포용 데이터 스냅샷 |
| `index.html` `static/` | 화면 |

## 환경변수

| 이름 | 필수 | 설명 |
|---|---|---|
| `LLM_API_KEY` | ✅ | 공급자 API 키. Render 는 서비스의 Environment 탭에 넣는다 |
| `LLM_BASE_URL` | ✅ | OpenAI 호환 엔드포인트 (아래 표 참조) |
| `LLM_MODEL` | ✅ | 모델 식별자 |
| `APP_PASSWORD` | ✅ | 접속 비밀번호. 실제 고객 도면 데이터라 인증 없이 띄우지 않는다 |

### 공급자별 설정

| 공급자 | `LLM_BASE_URL` | `LLM_MODEL` 예 | |
|---|---|---|---|
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.5-flash` | **기본값·검증됨** |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | 아래 참고 | 미검증 |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | 미검증 |

NVIDIA NIM 은 같은 코드로 붙지만 쓸 모델을 먼저 골라야 한다. 시도한 셋이
각각 과부하(`Service temporarily overloaded`), 사고 과정이 답변에 새는 문제,
계정 미지원(404) 이었다.

사용 가능한 모델 목록은 엔드포인트의 `/models` 로 확인한다.

```bash
curl -s $LLM_BASE_URL/models -H "Authorization: Bearer $LLM_API_KEY"
```

## 로컬 실행

```bash
pip install -r frontend/requirements.txt
export LLM_API_KEY=...
export LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
export LLM_MODEL=gemini-2.5-flash
export APP_PASSWORD=...
cd frontend && uvicorn server:app --reload --port 7860
```

`http://localhost:7860` 으로 접속한다.

## 데이터 갱신

파이프라인을 다시 돌려 대조 결과가 바뀌면 스냅샷을 갱신하고 커밋해야 배포에
반영된다. 서버는 `data/` 만 읽는다.

```bash
python3 frontend/refresh_data.py
```

## 배포 (Render)

리포지토리 루트의 `render.yaml` 이 Blueprint 다. Render 에서 리포를 연결하면
그대로 서비스가 만들어지고, `sync:false` 로 표시한 비밀은 대시보드에서 직접
입력받는다. 빌드 컨텍스트를 `frontend/` 로 좁혀 두어 도면 dxf 와 발주 엑셀은
이미지에 들어가지 않는다.

```
https://render.com/deploy?repo=https://github.com/gsitm52gLab/sung-ji-mes-dwg-to-excel
```

무료 플랜은 15분 비활동 시 슬립되고 깨어나는 데 약 1분 걸린다. 시연 전에 URL 을
한 번 열어 미리 깨워 두어야 한다. 월 750시간 한도가 있어 상시 운영용은 아니다.

`Dockerfile` 은 `PORT` 환경변수를 받는다. Render 는 `PORT` 를 주입하고(기본
10000) 그 포트에 `0.0.0.0` 으로 묶이지 않으면 배포를 실패 처리한다. 기본값을
7860 으로 두어 HF Spaces 규약도 함께 만족시킨다.

## 이번 범위 밖

우측 패널의 진행상황·도면 업로드·잔디 송부는 시안만 남기고 비활성이다
("데모" 배지). dwg 업로드와 파이프라인 실행, 예외 승인 기록도 아직 없다.
