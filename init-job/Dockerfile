FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir minio==7.2.7

COPY init.py /init.py

ENTRYPOINT ["python", "/init.py"]
