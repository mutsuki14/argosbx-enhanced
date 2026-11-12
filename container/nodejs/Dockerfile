# Build from the repository root:
# docker build -f container/nodejs/Dockerfile -t argosbx-enhanced .
FROM node:22-alpine
RUN apk add --no-cache bash curl openssl ca-certificates python3 coreutils procps gcompat libstdc++
WORKDIR /app
COPY container/nodejs/package*.json ./
RUN npm install --omit=dev
COPY container/nodejs/index.js container/nodejs/start.sh ./
COPY lib ./lib
RUN chmod 755 start.sh
EXPOSE 3000
CMD ["node", "index.js"]
