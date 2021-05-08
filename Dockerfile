
FROM python:3-alpine
LABEL maintainer="maurosoria@protonmail.com"
RUN apk add --no-cache --virtual .depends git
RUN git clone https://github.com/maurosoria/dirsearch.git
RUN apk del .depends
RUN pip install requests
ENTRYPOINT ["./dirsearch.py"]
CMD ["--help"]
