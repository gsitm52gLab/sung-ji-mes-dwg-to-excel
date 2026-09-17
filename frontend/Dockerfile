# 이 이미지 하나가 웹 서버이자 도면 변환기다.
#
# 리포지토리의 convert-dwg-to-dxf.sh 는 ODAFileConverter 를 별도 컨테이너로
# 띄우지만, 여기서는 그럴 수 없다. 이 서버 자체가 컨테이너 안이고 그 안에서
# Docker 를 또 띄울 수 없기 때문이다. 그래서 변환기를 같이 넣고 직접 부른다.
#
# ODAFileConverter 는 amd64 리눅스 전용 Qt GUI 앱이다. Render 는 amd64 라
# 에뮬레이션이 필요 없다. 화면이 없으므로 xvfb 로 가상 디스플레이를 붙인다.
#
# 빌드 컨텍스트는 리포지토리 루트다(render.yaml 의 dockerContext 참조).
# frontend/ 밖의 deckcheck 와 발주 엑셀이 필요하기 때문이다. 무거운 산출물은
# 루트 .dockerignore 로 걸러진다.
FROM --platform=linux/amd64 ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb libqt5widgets5 libqt5gui5 libqt5core5a \
      libxrender1 libxkbcommon-x11-0 \
      python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# ODA 변환기. deb 가 54MB 라 레이어를 따로 두어 코드 수정 시 재설치를 피한다.
COPY convert-dwg-to-dxf/ODAFileConverter_QT6_lnxX64_8.3dll_27.1.deb /tmp/oda.deb
RUN apt-get update && apt-get install -y --no-install-recommends /tmp/oda.deb \
    && rm /tmp/oda.deb && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY frontend/requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir -r requirements.txt

# 웹 앱
COPY frontend/ /app/
# 대조 엔진. pipeline.py 가 이 폴더를 cwd 로 두고 `python3 -m deckcheck` 를 부른다.
COPY convert-dxf-to-excel/deckcheck /app/deckcheck_pkg/deckcheck
# 대조 상대가 되는 발주 엑셀.
COPY arch-docs/excel /app/excel

# 포트는 호스트가 정한다. Render 는 PORT 를 주입하고(기본 10000) 그 포트에
# 0.0.0.0 으로 묶이지 않으면 배포를 실패 처리한다. HF Spaces 는 7860 을
# 기대한다. 그래서 PORT 를 받되 기본값을 7860 으로 두어 양쪽을 다 만족시킨다.
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
