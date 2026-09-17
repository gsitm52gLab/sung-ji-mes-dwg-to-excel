"""도면 검증 채팅 서버.

정적 파일을 서빙하고 `/api/chat` 에서 Gemini 응답을 SSE 로 흘린다.
대화 이력은 클라이언트가 들고 있고 서버는 무상태다. HF Space 는 재시작하면
디스크가 날아가므로 서버에 상태를 두지 않는 편이 맞다.

LLM 은 OpenAI 호환 엔드포인트면 무엇이든 붙는다. NVIDIA NIM, Gemini 의 OpenAI
호환 경로, OpenAI 본체가 모두 같은 코드로 돌아간다. 공급자를 바꾸는 일이 코드
수정이 아니라 환경변수 세 개를 고치는 일이어야 배포처에서 갈아끼울 수 있다.

환경변수:
    LLM_API_KEY   (필수) 공급자 API 키
    LLM_BASE_URL  (필수) OpenAI 호환 엔드포인트
                  NVIDIA  https://integrate.api.nvidia.com/v1
                  Gemini  https://generativelanguage.googleapis.com/v1beta/openai/
    LLM_MODEL     (필수) 모델 식별자
    APP_PASSWORD  (필수) 접속 비밀번호
    PORT          (선택) 기본 7860 — HF Spaces 기본 포트
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Iterator

from fastapi import Cookie, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from context import build_system_prompt

HERE = Path(__file__).resolve().parent
DATA_CSV = HERE / "data" / "구역별_대조.csv"

SESSION_COOKIE = "deckchat_session"

# 한 요청에 실어 보낼 수 있는 대화 이력의 상한. 무한정 늘어난 이력이
# 그대로 과금으로 이어지는 것을 막는다.
MAX_MESSAGES = 40
MAX_CHARS_PER_MESSAGE = 4000
MAX_OUTPUT_TOKENS = 1500


def _require_env(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"환경변수 {name} 가 설정되지 않았습니다. {hint}")
    return value


API_KEY = _require_env(
    "LLM_API_KEY",
    "Render 는 서비스의 Environment 탭에, 로컬은 셸에서 export 하세요.",
)
BASE_URL = _require_env(
    "LLM_BASE_URL",
    "OpenAI 호환 엔드포인트입니다. 예: https://integrate.api.nvidia.com/v1",
)
MODEL = _require_env(
    "LLM_MODEL",
    "모델 식별자입니다. 예: nvidia/nemotron-3-super-120b-a12b",
)
APP_PASSWORD = _require_env(
    "APP_PASSWORD",
    "접속 비밀번호입니다. 데이터가 실제 고객 도면이라 인증 없이 띄우지 않습니다.",
)

SYSTEM_PROMPT, DATA_META = build_system_prompt(DATA_CSV)


def _session_token() -> str:
    """비밀번호에서 유도한 세션 토큰.

    서버가 무상태라 세션 저장소를 두지 않는다. 비밀번호를 바꾸면 기존 세션이
    한꺼번에 무효가 되는데, 이 용도에서는 그게 바람직한 성질이다.
    """
    return hmac.new(
        APP_PASSWORD.encode("utf-8"), b"deckchat-session-v1", hashlib.sha256
    ).hexdigest()


SESSION_TOKEN = _session_token()


def _authed(token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token, SESSION_TOKEN)


app = FastAPI(title="데크 발주 검증 채팅")

# 클라이언트는 첫 요청 때 만든다. 기동만 시키고 네트워크가 없는 환경
# (빌드 단계 등)에서도 서버가 뜨게 하려는 것이다.
_client = None


def _llm_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=120.0)
    return _client


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _to_messages(messages: list[dict]) -> list[dict]:
    """채팅 이력을 OpenAI 형식 메시지 목록으로 바꾼다. 맨 앞에 시스템 프롬프트."""
    out = [{"role": "system", "content": SYSTEM_PROMPT}]
    for message in messages:
        text = (message.get("content") or "").strip()
        if not text:
            continue
        role = "assistant" if message.get("role") == "assistant" else "user"
        out.append({"role": role, "content": text[:MAX_CHARS_PER_MESSAGE]})
    return out


def _stream_reply(messages: list[dict]) -> Iterator[str]:
    try:
        stream = _llm_client().chat.completions.create(
            model=MODEL,
            messages=_to_messages(messages),
            stream=True,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        sent_any = False
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # 추론형 모델은 사고 과정을 reasoning_content 로 따로 낸다.
            # 그건 사용자에게 보여줄 것이 아니므로 content 만 흘린다.
            text = getattr(delta, "content", None)
            if text:
                sent_any = True
                yield _sse("token", {"text": text})
        if not sent_any:
            # 안전 필터 등으로 본문 없이 끝나는 경우. 빈 말풍선을 남기지 않는다.
            yield _sse("error", {"message": "모델이 빈 응답을 돌려줬습니다. 질문을 바꿔 다시 시도해 주세요."})
            return
        yield _sse("done", {})
    except Exception as exc:
        # 스트리밍이 시작된 뒤라 HTTP 상태코드를 바꿀 수 없다. 에러도 SSE 로 보낸다.
        name = type(exc).__name__
        detail = str(exc)
        if len(detail) > 300:
            detail = detail[:300] + "…"
        yield _sse("error", {"message": f"{name}: {detail}"})


@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    if not hmac.compare_digest(str(body.get("password", "")), APP_PASSWORD):
        raise HTTPException(status_code=401, detail="비밀번호가 맞지 않습니다.")
    response = JSONResponse({"ok": True})
    response.set_cookie(
        SESSION_COOKIE,
        SESSION_TOKEN,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return response


@app.get("/api/meta")
async def meta(deckchat_session: str | None = Cookie(default=None)):
    """로그인 여부와 대조 데이터 요약. 첫 화면을 그리는 데 쓴다."""
    if not _authed(deckchat_session):
        return {"authed": False}
    # BASE_URL 의 호스트만 싣는다. 키는 어떤 경우에도 내보내지 않는다.
    host = BASE_URL.split("//")[-1].split("/")[0]
    return {"authed": True, "model": MODEL, "provider": host, "data": DATA_META}


@app.post("/api/chat")
async def chat(request: Request, deckchat_session: str | None = Cookie(default=None)):
    if not _authed(deckchat_session):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    body = await request.json()
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages 가 비어 있습니다.")
    if len(messages) > MAX_MESSAGES:
        # 오래된 것부터 버린다. 최근 맥락이 답변에 더 중요하다.
        messages = messages[-MAX_MESSAGES:]

    return StreamingResponse(
        _stream_reply(messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/")
async def index():
    return FileResponse(HERE / "index.html")


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
