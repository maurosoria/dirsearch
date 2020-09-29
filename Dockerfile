
FROM python:3-alpine
LABEL maintainer="wfnintr@null.net"
WORKDIR /root
RUN apk add --no-cache --virtual .depends git 
RUN git clone https://github.com/maurosoria/dirsearch.git
RUN apk del .depends
WORKDIR /root/dirsearch
ENTRYPOINT ["./dirsearch.py"]
CMD ["--help"]
