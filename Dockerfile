# AURA OS — multi-stage: build frontend, serve everything from the backend.
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 AURA_DATA_DIR=/data
WORKDIR /app
# Litestream for continuous SQLite replication (used only when configured).
ARG TARGETARCH
ARG LITESTREAM_VERSION=0.3.13
ADD https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-${TARGETARCH:-amd64}.tar.gz /tmp/litestream.tgz
RUN tar -xzf /tmp/litestream.tgz -C /usr/local/bin litestream && rm /tmp/litestream.tgz
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY litestream.yml ./litestream.yml
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh
COPY --from=web /web/dist ./frontend/dist
VOLUME /data
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
