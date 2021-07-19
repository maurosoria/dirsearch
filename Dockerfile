FROM python:3-alpine
LABEL maintainer="maurosoria@protonmail.com"

WORKDIR /root/
ADD . /root/

RUN apk add \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev \
    libffi-dev

RUN pip install cryptography==2.8 \
    chardet \
    markupsafe \
    PySocks \
    urllib3 \
    certifi

ENTRYPOINT ["./dirsearch.py"]
CMD ["--help"]
