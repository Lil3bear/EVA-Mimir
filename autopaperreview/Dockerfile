FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git libfontconfig1 libfreetype6 perl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server ./server
COPY skills ./skills
COPY vendor ./vendor
COPY dist ./dist
COPY public ./public
ENV NODE_ENV=production BIND_HOST=0.0.0.0 PORT=4317 DATA_DIR=/data HOME=/tmp TEXMFVAR=/tmp/texmf-var TEXMFCONFIG=/tmp/texmf-config PATH=/opt/TinyTeX/bin/x86_64-linux:/usr/local/bin:/usr/bin:/bin
USER node
EXPOSE 4317
CMD ["node","server/index.mjs"]
