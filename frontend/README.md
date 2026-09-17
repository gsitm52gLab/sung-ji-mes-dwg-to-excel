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
대조한 결과를 놓고 Gemini 와 대화하는 화면이다.

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
| `GEMINI_API_KEY` | ✅ | Gemini API 키. HF 에서는 Settings > Variables and secrets 에 **Secret** 으로 |
| `APP_PASSWORD` | ✅ | 접속 비밀번호. 실제 고객 도면 데이터라 인증 없이 띄우지 않는다 |
| `GEMINI_MODEL` | | 기본 `gemini-2.5-flash` |

## 로컬 실행

```bash
pip install -r frontend/requirements.txt
export GEMINI_API_KEY=...
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

## 배포 (Hugging Face Spaces)

`frontend/` 가 곧 Space 루트다. subtree 로 밀어 넣는다.

```bash
git remote add hf https://huggingface.co/spaces/<계정>/<스페이스명>
git subtree push --prefix=frontend hf main
```

Space 는 **Private** 으로 만든다. 데이터가 실제 고객(대우건설 식사푸르지오)
도면이기 때문이다. 앱 비밀번호는 그 위에 한 겹 더 두는 것이다.

## 이번 범위 밖

우측 패널의 진행상황·도면 업로드·잔디 송부는 시안만 남기고 비활성이다
("데모" 배지). dwg 업로드와 파이프라인 실행, 예외 승인 기록도 아직 없다.
