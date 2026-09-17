# HF Spaces 는 컨테이너를 UID 1000 으로 돌린다. 그래서 같은 UID 의 사용자를
# 먼저 만들고, 이후 COPY 는 전부 --chown=user 로 받는다. 이 순서를 어기면
# 권한 오류가 난다.
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

# HF Spaces 기본 노출 포트. README 의 app_port 와 맞춰야 한다.
EXPOSE 7860
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
