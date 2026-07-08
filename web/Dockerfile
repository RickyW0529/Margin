# Frontend web image for Margin (Next.js).
FROM node:20-slim

WORKDIR /app

# Install dependencies before copying source so npm_modules can be cached.
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund --fetch-retries=5 --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=120000

COPY ./ ./
RUN npm run build
# Remove dev dependencies to reduce final image size.
RUN npm prune --omit=dev
RUN chown -R node:node /app

ENV NODE_ENV=production

USER node

EXPOSE 3000

CMD ["npm", "start"]
