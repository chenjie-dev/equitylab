# build context = 仓库根
FROM node:20-alpine AS deps
WORKDIR /build
COPY packages/qdb-ts ./packages/qdb-ts
COPY apps/frontend/package.json apps/frontend/package-lock.json* ./apps/frontend/
WORKDIR /build/apps/frontend
RUN npm install

FROM node:20-alpine AS build
WORKDIR /build
COPY --from=deps /build/packages/qdb-ts ./packages/qdb-ts
COPY --from=deps /build/apps/frontend/node_modules ./apps/frontend/node_modules
COPY apps/frontend ./apps/frontend
# file: 依赖指向 ../../packages/qdb-ts，保持相对路径
WORKDIR /build/apps/frontend
ENV NEXT_TELEMETRY_DISABLED=1
# next.config rewrites 编译进 standalone；运行时由容器访问 Docker DNS `gateway`
ENV GATEWAY_URL=http://gateway:3000
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup -S app && adduser -S -G app -u 10001 appuser
COPY --from=build --chown=appuser:app /build/apps/frontend/public ./public
COPY --from=build --chown=appuser:app /build/apps/frontend/.next/standalone ./
COPY --from=build --chown=appuser:app /build/apps/frontend/.next/static ./.next/static
USER appuser
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=10 \
  CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]
