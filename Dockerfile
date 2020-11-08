
FROM python:3-alpine
LABEL maintainer="maurosoria@protonmail.com"
WORKDIR /root
RUN apk add --no-cache --virtual .depends git
RUN git clone https://github.com/maurosoria/dirsearch.git
RUN apk del .depends
WORKDIR /root/dirsearch
RUN pip install requests
ENTRYPOINT ["./dirsearch.py"]
CMD ["--help"]
