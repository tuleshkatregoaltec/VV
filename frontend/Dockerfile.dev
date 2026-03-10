FROM oven/bun:1-alpine

WORKDIR /app/frontend

COPY frontend/package.json frontend/bun.lock /app/frontend/

RUN bun install

COPY frontend /app/frontend

EXPOSE 5173

CMD ["bun", "run", "dev", "--host", "0.0.0.0"]
