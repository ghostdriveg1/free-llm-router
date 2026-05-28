FROM alpine:3.19

# 1. Install System Dependencies (Redis, Git, Curl, Python3)
RUN apk add --no-cache \
    redis \
    git \
    curl \
    python3 \
    py3-pip \
    libevent \
    libevent-dev \
    gcc \
    make \
    musl-dev \
    bsd-compat-headers

# 2. Compile Webdis REST Gateway from source
RUN git clone --depth 1 https://github.com/nicolasff/webdis.git /tmp/webdis \
    && cd /tmp/webdis \
    && make \
    && cp webdis /usr/local/bin/ \
    && rm -rf /tmp/webdis

# 3. Clean up compile dependencies to keep image size small
RUN apk del gcc make musl-dev libevent-dev bsd-compat-headers

# 4. Install Boto3 for Cloudflare R2 AWS S3 integrations
RUN pip install --no-cache-dir --break-system-packages boto3

# 5. Create app directories and copy configurations
WORKDIR /app
COPY webdis.json /app/webdis.json
COPY entrypoint.sh /app/entrypoint.sh
COPY backup.py /app/backup.py

RUN chmod +x /app/entrypoint.sh

# Expose Webdis HTTP Port (Hugging Face default)
EXPOSE 7860

ENTRYPOINT ["/app/entrypoint.sh"]
