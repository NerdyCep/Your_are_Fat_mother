# dashboard/Dockerfile

# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm i
COPY tsconfig.json ./
COPY src ./src
COPY public ./public
# bundle -> dist/main.js
RUN npx esbuild src/main.tsx \
    --bundle --outdir=dist \
    --loader:.tsx=tsx --loader:.ts=ts \
    --jsx=automatic --minify

# ---- serve stage ----
FROM nginx:1.25-alpine
# статика и бандл
COPY --from=build /app/public /usr/share/nginx/html
COPY --from=build /app/dist /usr/share/nginx/html/dist
# nginx конфиг: /api -> backend, /dist -> статика, / -> SPA
COPY nginx.conf /etc/nginx/conf.d/default.conf
