FROM mcr.microsoft.com/playwright:v1.58.2-noble

WORKDIR /work/e2e

COPY e2e/package.json /work/e2e/package.json

RUN npm install

CMD ["bash", "-lc", "tail -f /dev/null"]
