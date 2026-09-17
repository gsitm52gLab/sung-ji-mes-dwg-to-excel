"""도면 검증 채팅 서버.

정적 파일을 서빙하고 `/api/chat` 에서 Gemini 응답을 SSE 로 흘린다.
대화 이력은 클라이언트가 들고 있고 서버는 무상태다. HF Space 는 재시작하면
디스크가 날아가므로 서버에 상태를 두지 않는 편이 맞다.

환경변수:
    GEMINI_API_KEY  (필수) Gemini API 키
    APP_PASSWORD    (필수) 접속 비밀번호
    GEMINI_MODEL    (선택) 기본 gemini-2.5-flash
    PORT            (선택) 기본 7860 — HF Spaces 기본 포트
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

DEFAULT_MODEL = "gemini-2.5-flash"
SESSION_COOKIE = "deckchat_session"

# 한 요청에 실어 보낼 수 있는 대화 이력의 상한. 무한정 늘어난 이력이
# 그대로 과금으로 이어지는 것을 막는다.
MAX_MESSAGES = 40
MAX_CHARS_PER_MESSAGE = 4000


def _require_env(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"환경변수 {name} 가 설정되지 않았습니다. {hint}")
    return value


API_KEY = _require_env(
    "GEMINI_API_KEY",
    "HF Space 는 Settings > Variables and secrets 에, 로컬은 셸에서 export 하세요.",
)
APP_PASSWORD = _require_env(
    "APP_PASSWORD",
    "접속 비밀번호입니다. 데이터가 실제 고객 도면이라 인증 없이 띄우지 않습니다.",
)
MODEL = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL

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

# google-genai 클라이언트는 첫 요청 때 만든다. 기동만 시키고 네트워크가
# 없는 환경(빌드 단계 등)에서도 서버가 뜨게 하려는 것이다.
_client = None


def _gemini_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=API_KEY)
    return _client


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _to_contents(messages: list[dict]):
    """채팅 이력을 google-genai 의 Content 목록으로 바꾼다."""
    from google.genai import types

    contents = []
    for message in messages:
        text = (message.get("content") or "").strip()
        if not text:
            continue
        # Gemini 는 assistant 를 'model' 로 부른다.
        role = "model" if message.get("role") == "assistant" else "user"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=text[:MAX_CHARS_PER_MESSAGE])])
        )
    return contents


def _stream_reply(messages: list[dict]) -> Iterator[str]:
    from google.genai import types

    try:
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            # 도구를 붙이지 않았으므로 자동 함수 호출을 꺼 경고를 없앤다.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )
        stream = _gemini_client().models.generate_content_stream(
            model=MODEL, contents=_to_contents(messages), config=config
        )
        sent_any = False
        for chunk in stream:
            text = getattr(chunk, "text", None)
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
    return {"authed": True, "model": MODEL, "data": DATA_META}


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
