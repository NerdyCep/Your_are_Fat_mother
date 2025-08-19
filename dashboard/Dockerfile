# build
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# если есть lock — используем ci; если нет — обычный install
RUN if [ -f package-lock.json ]; then npm ci; else npm i --no-audit --no-fund; fi
COPY public ./public
COPY src ./src
COPY tsconfig.json ./tsconfig.json
RUN npm run build

# serve (nginx) + proxy /api -> http://api:8000
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
