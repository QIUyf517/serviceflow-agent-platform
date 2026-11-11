FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/index.html ./index.html
COPY frontend/tsconfig*.json ./
COPY frontend/vite.config.ts frontend/eslint.config.js ./
COPY frontend/src ./src
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=5s --timeout=3s --retries=20 CMD wget --quiet --tries=1 --spider http://127.0.0.1/healthz || exit 1
