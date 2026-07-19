# Secure Document Room — frontend (Next.js 14)
# NEXT_PUBLIC_* values are inlined at BUILD time, so the public origin of the
# deployment must be passed as a build arg (docker-compose.prod.yml wires it
# from ${PUBLIC_ORIGIN}). The app's API paths already include the /api prefix
# and Caddy proxies /api/* to the backend on the same origin.

# ---- build stage ----
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# e.g. https://confidant-xxxx.westeurope.cloudapp.azure.com
# Pass "/" for same-origin relative API calls — the sandbox image builds with
# NEXT_PUBLIC_API_URL="/" so one image works behind any FQDN (Caddy proxies
# /api/* on the same origin; api.ts strips the trailing slash to ""). An
# empty value would NOT work: Next 14.2 skips inlining falsy NEXT_PUBLIC_*
# values. Leaving the arg UNSET falls back to http://localhost:8000 for local
# dev (see src/lib/api.ts, ?? semantics).
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ---- runtime stage ----
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.mjs ./

EXPOSE 3000
CMD ["npm", "run", "start"]
