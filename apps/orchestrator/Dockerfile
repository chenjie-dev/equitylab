FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY tsconfig.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup -S app && adduser -S -G app -u 10001 appuser
COPY --from=build --chown=appuser:app /app/node_modules ./node_modules
COPY --from=build --chown=appuser:app /app/dist ./dist
COPY --chown=appuser:app package.json ./
USER appuser
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=10 \
  CMD wget -qO- http://127.0.0.1:8001/health >/dev/null || exit 1
CMD ["node", "dist/index.js"]
