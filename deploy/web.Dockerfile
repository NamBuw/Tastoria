# syntax=docker/dockerfile:1.7
# nginx image with the Expo web export baked in. Build context: repository root (web.Dockerfile.dockerignore).

FROM node:22-bookworm-slim AS web
WORKDIR /app
COPY app/package.json app/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY app/ ./
# Same origin as the API: nginx proxies /api/ (spec v2 §10). The app is served at the domain root.
ENV EXPO_PUBLIC_API_URL=/api/v1 \
    EXPO_NO_TELEMETRY=1 \
    CI=1
RUN npx expo export --platform web --output-dir dist

FROM nginx:1.28-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY deploy/nginx/tastoria.conf /etc/nginx/conf.d/tastoria.conf
COPY --from=web /app/dist /usr/share/nginx/tastoria
# Landing page /gioi-thieu/ (static, landing/nginx-snippet.conf is inlined in tastoria.conf)
COPY landing/index.html landing/style.css /usr/share/nginx/landing/
COPY landing/fonts /usr/share/nginx/landing/fonts
COPY landing/img /usr/share/nginx/landing/img
