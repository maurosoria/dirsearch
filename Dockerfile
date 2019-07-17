FROM python:3
MAINTAINER greenmind.sec@gmail.com
RUN apt-get update -y
RUN apt-get install python3-pip -y
WORKDIR /root
ADD . .
WORKDIR /root/
RUN chmod +x dirsearch.py
ENTRYPOINT ["/root/dirsearch.py"]
CMD ["--help"]
