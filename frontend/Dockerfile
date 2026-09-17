# HF Spaces 는 컨테이너를 UID 1000 으로 돌린다. 그래서 같은 UID 의 사용자를
# 먼저 만들고, 이후 COPY 는 전부 --chown=user 로 받는다. 이 순서를 어기면
# 권한 오류가 난다. Render 는 UID 를 따지지 않으므로 이대로 두어도 무방하다.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# 포트는 호스트가 정한다. Render 는 PORT 를 주입하고(기본 10000) 그 포트에
# 0.0.0.0 으로 묶이지 않으면 배포를 실패 처리한다. HF Spaces 는 7860 을
# 기대한다. 그래서 PORT 를 받되 기본값을 7860 으로 두어 양쪽을 다 만족시킨다.
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
