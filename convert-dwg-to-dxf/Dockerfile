FROM --platform=linux/amd64 ubuntu:22.04

RUN apt-get update && apt-get install -y \
    xvfb libqt5widgets5 libqt5gui5 libqt5core5a \
    libxrender1 libxkbcommon-x11-0 wget \
    && rm -rf /var/lib/apt/lists/*

COPY ODAFileConverter_QT6_lnxX64_8.3dll_27.1.deb /tmp/oda.deb
RUN apt-get update && apt-get install -y /tmp/oda.deb && rm /tmp/oda.deb

RUN pip3 install ezdxf || (apt-get update && apt-get install -y python3-pip && pip3 install ezdxf)

WORKDIR /work

