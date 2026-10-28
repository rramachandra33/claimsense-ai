# The Ops Console (Next.js). Built by the root docker-compose.yml (make stack).
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim
ENV NODE_ENV=production
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/.next .next
COPY next.config.mjs ./
USER node
EXPOSE 3100
CMD ["node_modules/.bin/next", "start", "-p", "3100"]
