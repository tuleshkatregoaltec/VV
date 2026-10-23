#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { chromium } = require("../../e2e/node_modules/playwright");

const { browserEndpoint, ensureAuthenticated, isAuthenticated } = require("./dxbi_browser_session");
const OUTPUT_DIR = process.env.DXBI_SALES_OUTPUT_DIR || path.resolve(__dirname, "../var/dxbi-sales");
const STATE_PATH = process.env.DXBI_SALES_STATE_PATH || path.join(OUTPUT_DIR, "checkpoint.json");
const COMPOSE_DIR =
  process.env.DXBI_SALES_COMPOSE_DIR || path.resolve(__dirname, "../..");
const START_DATE = process.env.DXBI_SALES_START_DATE || "2007-01-01";
const END_DATE = process.env.DXBI_SALES_END_DATE || new Date().toISOString().slice(0, 10);
const ORDER = String(process.env.DXBI_SALES_ORDER || "desc").toLowerCase();
if (!new Set(["asc", "desc"]).has(ORDER)) {
  throw new Error("DXBI_SALES_ORDER must be either asc or desc");
}
const BUCKET_SIZE = Number(process.env.DXBI_SALES_BUCKET_SIZE || 250);
const PAGE_SIZE = Number(process.env.DXBI_SALES_PAGE_SIZE || 300);
const MAX_REQUESTS = Number(process.env.DXBI_SALES_MAX_REQUESTS || 15000);
const DELAY_MIN_MS = Number(process.env.DXBI_SALES_DELAY_MIN_MS || 2500);
const DELAY_MAX_MS = Number(process.env.DXBI_SALES_DELAY_MAX_MS || 5500);
const LOCATION_ID = process.env.DXBI_SALES_LOCATION_ID || "1";
const LOCATION_TEXT = process.env.DXBI_SALES_LOCATION_TEXT || "Dubai";
const LOCATION_SLUG = process.env.DXBI_SALES_LOCATION_SLUG || "dubai";

const REPORT = {
  name: "sales",
  reportId: "report_soldhistory",
  regionName: "soldhistory",
  tableId: "report_table_soldhistory",
  regionMarker: "29609740940913885923",
};

function clean(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function nowStamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelayMs() {
  if (DELAY_MAX_MS <= DELAY_MIN_MS) return DELAY_MIN_MS;
  return DELAY_MIN_MS + Math.floor(Math.random() * (DELAY_MAX_MS - DELAY_MIN_MS + 1));
}

function loadState() {
  if (!fs.existsSync(STATE_PATH)) {
    return { version: 1, completed_buckets: {}, fallback_pages: {}, failed_buckets: {} };
  }
  return JSON.parse(fs.readFileSync(STATE_PATH, "utf8"));
}

function saveState(state) {
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  fs.writeFileSync(STATE_PATH, `${JSON.stringify(state, null, 2)}\n`);
}

function bucketKey(bucket) {
  return `${bucket.date}|${bucket.bucket}|${bucket.min_price}|${bucket.max_price}`;
}

function queryBucketPlan() {
  const query = `
WITH per_row AS (
  SELECT
    toDate(instance_date) AS d,
    trans_value,
    intDiv(row_number() OVER (PARTITION BY toDate(instance_date) ORDER BY trans_value, transaction_number) - 1, ${BUCKET_SIZE}) AS bucket
  FROM dld_od_transactions_bronze
  WHERE group_en = 'Sales'
    AND toDate(instance_date) BETWEEN toDate('${START_DATE}') AND toDate('${END_DATE}')
),
buckets AS (
  SELECT
    d,
    bucket,
    min(trans_value) AS min_price,
    max(trans_value) AS max_price,
    count() AS local_rows
  FROM per_row
  GROUP BY d, bucket
)
SELECT
  toString(d) AS date,
  bucket,
  min_price,
  max_price,
  local_rows
FROM buckets
ORDER BY d ${ORDER.toUpperCase()}, bucket ASC
FORMAT JSONEachRow`;

  const output = execFileSync(
    "docker",
    ["compose", "exec", "-T", "clickhouse", "clickhouse-client", "--database", "vitevue", "--query", query],
    { cwd: COMPOSE_DIR, encoding: "utf8", maxBuffer: 128 * 1024 * 1024 },
  );
  return output
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function parsePaginateHref(href) {
  const pattern = /apex\.widget\.report\.paginate\('([^']+)'\s*,\s*'([^']+)'\s*,\s*\{min:(\d+),max:(\d+),fetched:(\d+)\}\)/;
  const match = String(href || "").match(pattern);
  if (!match) return null;
  return {
    regionId: match[1],
    pageSize: Number(match[5]) || Number(match[4]) || 13,
  };
}

function parseUnitNumber(text) {
  const matches = [...clean(text).matchAll(/\bNo\.\s*([^,]+)/gi)]
    .map((match) => clean(match[1]))
    .filter(Boolean);
  const unit = matches.at(-1) || "";
  return /^u-hidden$/i.test(unit) ? "" : unit;
}

async function findDxbPage(browser) {
  const context = browser.contexts()[0];
  if (!context) throw new Error("No browser context found in the remote-debug Chrome session.");
  const pages = context.pages().filter((candidate) => !candidate.isClosed());
  let page = pages.find(
    (candidate) =>
      new URL(candidate.url()).origin === "https://dxbinteract.com" &&
      new URL(candidate.url()).pathname === "/",
  );
  page ||= await context.newPage();
  if (!page.url().includes("dxbinteract.com") || page.url().includes("/valuation/")) {
    await page.goto("https://dxbinteract.com/", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
  }
  return page;
}

function isRecoverablePageError(error) {
  return /Execution context was destroyed|Target page, context or browser has been closed|Navigation|Failed to fetch|ERR_CONNECTION_CLOSED|ERR_CONNECTION_RESET|ERR_NETWORK_CHANGED/i.test(
    String(error?.message || error),
  );
}

async function ensureTransactionRegion(page) {
  const ok = await page.evaluate(() => Boolean(document.querySelector("#report_soldhistory")));
  if (ok) return;
  await page.goto("https://dxbinteract.com/", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  const retry = await page.evaluate(() => Boolean(document.querySelector("#report_soldhistory")));
  if (!retry) throw new Error("DXB sales report not found after reload");
}

async function applyFilters(page, bucket) {
  await page.evaluate(
    ({ date, minPrice, maxPrice, locationId, locationText, locationSlug }) => {
      if (typeof window.$s !== "function") throw new Error("APEX $s is not available");
      const set = (id, value) => {
        if (document.querySelector(`#${id}`)) window.$s(id, value, null, true);
      };
      set("P74_DLD_LOCATION_ID", locationId);
      set("P74_DLD_LOCATION_TEXT", locationText);
      set("P74_DLD_LOCATION", locationSlug);
      set("P74_START_DATE", date);
      set("P74_END_DATE", date);
      set("P74_DEAL", "SALE");
      set("P74_MIN_PRICE", String(minPrice));
      set("P74_MAX_PRICE", String(maxPrice));
      set("P74_PROJECT", "");
      set("P74_PROJECT_A", "");
      set("P74_PROJECT_A_HIDDENVALUE", "");
      set("P74_MY_PROJECT", "");
      set("P74_MY_PROJECT_HIDDENVALUE", "");
    },
    {
      date: bucket.date,
      minPrice: bucket.min_price,
      maxPrice: bucket.max_price,
      locationId: LOCATION_ID,
      locationText: LOCATION_TEXT,
      locationSlug: LOCATION_SLUG,
    },
  );
}

async function refreshSales(page) {
  await page.evaluate(() => {
    if (!window.apex?.region) throw new Error("APEX region API is not available");
    window.apex.region("soldhistory").refresh();
  });
  await page.waitForTimeout(2200);
}

async function captureTemplate(page) {
  const linkInfo = await page.evaluate(() => {
    const reportEl = document.querySelector("#report_soldhistory");
    if (!reportEl) return { ok: false, retryable: true, reason: "missing #report_soldhistory" };
    const link = [...reportEl.querySelectorAll('a[href*="apex.widget.report.paginate"]')][0];
    if (!link) return { ok: false, retryable: false, reason: "missing paginate link" };
    return { ok: true, href: link.getAttribute("href") || "" };
  });
  if (!linkInfo.ok) return linkInfo;

  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().includes("/wwv_flow.ajax?p_context=litedxb/transactions/") &&
      (request.postData() || "").includes(REPORT.regionMarker),
    { timeout: 10000 },
  );
  await page.evaluate(() => {
    document.querySelector('#report_soldhistory a[href*="apex.widget.report.paginate"]').click();
  });
  const request = await requestPromise;
  const parsed = parsePaginateHref(linkInfo.href);
  if (!parsed) throw new Error("could not parse sales pagination href");
  return { ok: true, url: request.url(), postData: request.postData() || "", ...parsed };
}

async function fetchRows(page, template, bucket, { minRow = 1, maxRows = PAGE_SIZE, fetched = PAGE_SIZE } = {}) {
  return page.evaluate(
    async ({ template, bucket, minRow, maxRows, fetched, report, locationId, locationText, locationSlug }) => {
      const params = new URLSearchParams(template.postData);
      params.set("p_pg_min_row", String(minRow));
      params.set("p_pg_max_rows", String(maxRows));
      params.set("p_pg_rows_fetched", String(fetched));
      params.set("x01", template.regionId);
      const payload = JSON.parse(params.get("p_json"));
      for (const item of payload.pageItems?.itemsToSubmit || []) {
        if (item.n === "P74_DLD_LOCATION_ID") item.v = locationId;
        if (item.n === "P74_DLD_LOCATION_TEXT") item.v = locationText;
        if (item.n === "P74_DLD_LOCATION") item.v = locationSlug;
        if (item.n === "P74_START_DATE") item.v = bucket.date;
        if (item.n === "P74_END_DATE") item.v = bucket.date;
        if (item.n === "P74_DEAL") item.v = "SALE";
        if (item.n === "P74_MIN_PRICE") item.v = String(bucket.min_price);
        if (item.n === "P74_MAX_PRICE") item.v = String(bucket.max_price);
      }
      params.set("p_json", JSON.stringify(payload));
      const response = await fetch(template.url, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
          "X-Requested-With": "XMLHttpRequest",
          Accept: "text/html, */*; q=0.01",
        },
        body: params.toString(),
      });
      const html = await response.text();
      if (/P9999_USERNAME|apex_authentication/i.test(html)) {
        return { status: response.status, loginRedirect: true, rows: [], byte_length: html.length };
      }
      const doc = new DOMParser().parseFromString(html, "text/html");
      const table = doc.querySelector(`#${report.tableId}`);
      const headers = {};
      if (table) {
        table.querySelectorAll("thead th").forEach((th) => {
          if (th.id) headers[th.id] = (th.innerText || th.textContent || "").replace(/\s+/g, " ").trim();
        });
      }
      const rows = table
        ? [...table.querySelectorAll("tbody tr")].map((tr, rowIndex) => ({
            row_index_in_response: rowIndex + 1,
            columns: [...tr.querySelectorAll("td")].map((td) => {
              const header = td.getAttribute("headers") || "";
              return {
                id: header,
                label: headers[header] || "",
                text: (td.innerText || td.textContent || "").replace(/\s+/g, " ").trim(),
                html: td.innerHTML || "",
                location_titles: [...new Set([...td.querySelectorAll('span.bold-title[title]')].map(el => el.getAttribute('title').trim()).filter(Boolean))],
                links: [...td.querySelectorAll("a[href]")].map((a) => ({
                  text: (a.innerText || a.textContent || "").replace(/\s+/g, " ").trim(),
                  href: a.href || a.getAttribute("href") || "",
                  class: a.getAttribute("class") || "",
                })),
              };
            }),
          }))
        : [];
      return { status: response.status, loginRedirect: false, rows, byte_length: html.length };
    },
    {
      template,
      bucket,
      minRow,
      maxRows,
      fetched,
      report: REPORT,
      locationId: LOCATION_ID,
      locationText: LOCATION_TEXT,
      locationSlug: LOCATION_SLUG,
    },
  );
}

function rowToRecord({ bucket, row }) {
  const byId = Object.fromEntries(row.columns.map((column) => [column.id, column]));
  const locationText = byId.PATH_NAME?.text || "";
  const specsText = byId.BEDROOM?.text || "";
  const amountText = byId.TOTAL_PRICE?.text || "";
  const dateText = byId.SOLD_BY?.text || "";
  const links = row.columns.flatMap((column) => column.links || []);
  return {
    transaction_type: "sales",
    bucket_date: bucket.date,
    bucket_index: bucket.bucket,
    bucket_min_price: bucket.min_price,
    bucket_max_price: bucket.max_price,
    bucket_local_rows: bucket.local_rows,
    dld_transaction_number: clean(byId.TRANSACTION_NUMBER?.text),
    unit_number: parseUnitNumber(locationText),
    location_text: clean(locationText),
    ...(byId.PATH_NAME?.location_titles?.length === 1
      ? { location_title: clean(byId.PATH_NAME.location_titles[0]) } : {}),
    amount_text: clean(amountText),
    specs_text: clean(specsText),
    date_text: clean(dateText),
    detail_url: links.find((link) => /\/sold\/t-/.test(link.href))?.href || "",
    columns: row.columns,
  };
}

async function run() {
  if (process.argv.includes("--sample")) {
    const browser = await chromium.connectOverCDP(browserEndpoint());
    const page = await browser.contexts()[0].newPage();
    try {
      await page.goto("https://dxbinteract.com/", { waitUntil: "domcontentloaded" });
      await ensureAuthenticated(page);
      console.log(JSON.stringify(await captureSalesSample(page, OUTPUT_DIR)));
    } finally {
      await page.close();
      await browser.close(); // Disconnects this CDP client; leaves the user's browser running.
    }
    return;
  }
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  const state = loadState();
  const buckets = queryBucketPlan();
  const stamp = nowStamp();
  const jsonlPath = path.join(OUTPUT_DIR, `dxbi_sales_dynamic_${stamp}.jsonl`);
  const summaryPath = path.join(OUTPUT_DIR, `dxbi_sales_dynamic_${stamp}_summary.json`);
  const stream = fs.createWriteStream(jsonlPath, { flags: "a", encoding: "utf8" });
  const summary = {
    started_at: new Date().toISOString(),
    output_jsonl: jsonlPath,
    checkpoint: STATE_PATH,
    planned_buckets: buckets.length,
    requests: 0,
    completed_buckets: 0,
    fallback_buckets: 0,
    rows: 0,
    stopped_reason: "",
  };

  const browser = await chromium.connectOverCDP(browserEndpoint());
  try {
    let page = await findDxbPage(browser);

    async function recoverPage(reason) {
      console.error(`${reason}: acquiring a fresh DXB scraper tab`);
      const context = browser.contexts()[0];
      if (!context) throw new Error("DXB browser context is unavailable during page recovery");
      page = await context.newPage();
      await page.goto("https://dxbinteract.com/", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3000);
      await ensureAuthenticated(page, reason);
      await ensureTransactionRegion(page);
    }

    try {
      await ensureAuthenticated(page, "startup");
      await ensureTransactionRegion(page);
    } catch (error) {
      if (!isRecoverablePageError(error)) throw error;
      await recoverPage("startup recovery");
    }

    async function prepareBucket(bucket) {
      for (let pageAttempt = 1; pageAttempt <= 3; pageAttempt += 1) {
        try {
          await ensureAuthenticated(page, `${bucketKey(bucket)} prepare`);
          await ensureTransactionRegion(page);
          await applyFilters(page, bucket);
          await refreshSales(page);
          let template = await captureTemplate(page);
          for (let attempt = 1; template.retryable && attempt <= 3; attempt += 1) {
            console.error(`${bucketKey(bucket)}: retry ${attempt} after ${template.reason}`);
            await page.goto("https://dxbinteract.com/", { waitUntil: "domcontentloaded" });
            await page.waitForTimeout(3000);
            await ensureAuthenticated(page, `${bucketKey(bucket)} prepare retry`);
            await ensureTransactionRegion(page);
            await applyFilters(page, bucket);
            await refreshSales(page);
            template = await captureTemplate(page);
          }
          return template;
        } catch (error) {
          if (!isRecoverablePageError(error) || pageAttempt === 3) throw error;
          const message = String(error?.message || error).split("\n")[0];
          await recoverPage(`${bucketKey(bucket)} prepare retry ${pageAttempt} after ${message}`);
        }
      }
      throw new Error(`${bucketKey(bucket)}: page recovery exhausted`);
    }

    async function fetchRowsWithRetry(bucket, template, options = {}) {
      let currentTemplate = template;
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        try {
          const response = await fetchRows(page, currentTemplate, bucket, options);
          if (!response.loginRedirect) return { response, template: currentTemplate };
          console.error(`${bucketKey(bucket)}: login redirect during fetch; attempting session recovery`);
          await ensureAuthenticated(page, `${bucketKey(bucket)} login redirect`);
          currentTemplate = await prepareBucket(bucket);
          if (!currentTemplate.ok) {
            throw new Error(`${bucketKey(bucket)}: ${currentTemplate.reason}`);
          }
        } catch (error) {
          const message = String(error?.message || error);
          if (!isRecoverablePageError(error) || attempt === 3) {
            throw error;
          }
          console.error(`${bucketKey(bucket)}: fetch retry ${attempt} after ${message.split("\n")[0]}`);
          await recoverPage(`${bucketKey(bucket)} fetch retry ${attempt}`);
          await ensureTransactionRegion(page);
          currentTemplate = await prepareBucket(bucket);
          if (!currentTemplate.ok) {
            throw new Error(`${bucketKey(bucket)}: ${currentTemplate.reason}`);
          }
        }
      }
      throw new Error(`${bucketKey(bucket)}: fetch retry exhausted`);
    }

    for (const bucket of buckets) {
      const key = bucketKey(bucket);
      if (state.completed_buckets[key]) continue;
      if (state.failed_buckets[key]) continue;
      if (summary.requests >= MAX_REQUESTS) {
        summary.stopped_reason = "max_requests_reached";
        return;
      }

      let template = await prepareBucket(bucket);
      if (!template.ok) {
        state.failed_buckets[key] = { reason: template.reason, failed_at: new Date().toISOString() };
        saveState(state);
        continue;
      }

      let fetched = await fetchRowsWithRetry(bucket, template);
      let response = fetched.response;
      template = fetched.template;
      summary.requests += 1;
      if (response.loginRedirect) throw new Error(`${key}: login redirect`);
      if (response.status >= 400) throw new Error(`${key}: HTTP ${response.status}`);
      await sleep(randomDelayMs());

      let rows = response.rows;
      if (rows.length >= PAGE_SIZE) {
        summary.fallback_buckets += 1;
        rows = [];
        const pageSize = template.pageSize || 13;
        for (let minRow = 1; ; minRow += pageSize) {
          if (summary.requests >= MAX_REQUESTS) {
            summary.stopped_reason = "max_requests_reached";
            return;
          }
          const pageKey = `${key}|min=${minRow}`;
          if (state.fallback_pages[pageKey]) {
            if (state.fallback_pages[pageKey].rows < pageSize) break;
            continue;
          }
          fetched = await fetchRowsWithRetry(bucket, template, {
            minRow,
            maxRows: pageSize,
            fetched: pageSize,
          });
          response = fetched.response;
          template = fetched.template;
          summary.requests += 1;
          if (response.loginRedirect) throw new Error(`${pageKey}: login redirect`);
          if (response.status >= 400) throw new Error(`${pageKey}: HTTP ${response.status}`);
          rows.push(...response.rows);
          state.fallback_pages[pageKey] = {
            rows: response.rows.length,
            completed_at: new Date().toISOString(),
          };
          saveState(state);
          await sleep(randomDelayMs());
          if (response.rows.length < pageSize) break;
        }
      }

      for (const row of rows) stream.write(`${JSON.stringify(rowToRecord({ bucket, row }))}\n`);
      state.completed_buckets[key] = {
        rows: rows.length,
        local_rows: bucket.local_rows,
        completed_at: new Date().toISOString(),
      };
      saveState(state);
      summary.completed_buckets += 1;
      summary.rows += rows.length;
      console.error(
        `sales ${bucket.date} bucket=${bucket.bucket} ${bucket.min_price}-${bucket.max_price}: ${rows.length} rows`,
      );
    }
    summary.stopped_reason = "completed_range";
  } finally {
    summary.finished_at = new Date().toISOString();
    stream.end();
    await new Promise((resolve) => stream.on("finish", resolve));
    fs.writeFileSync(summaryPath, `${JSON.stringify(summary, null, 2)}\n`);
    if (typeof browser.disconnect === "function") await browser.disconnect();
    console.log(JSON.stringify({ jsonlPath, summaryPath, summary }, null, 2));
  }
}

async function captureSalesSample(page, outputDir) {
  await ensureAuthenticated(page);
  await page.locator("#report_table_soldhistory tbody tr").first().waitFor({ timeout: 30000 });
  const rows = await page.locator("#report_table_soldhistory tbody tr").evaluateAll(trs =>
    trs.slice(0, 13).map(tr => ({ columns: [...tr.querySelectorAll("td")].map(td => ({
      id: td.getAttribute("headers") || "",
      text: (td.innerText || "").replace(/\s+/g, " ").trim(),
      html: td.innerHTML,
      location_titles: [...new Set([...td.querySelectorAll('span.bold-title[title]')].map(el => el.getAttribute('title').trim()).filter(Boolean))],
      links: [...td.querySelectorAll("a[href]")].map(a => ({ href: a.href, text: a.innerText })),
    })) })),
  );
  // A sample of the current report, not a completed date/price bucket or checkpoint.
  const records = rows.map(row => ({
    ...rowToRecord({ bucket: {}, row }),
    scraped_at: new Date().toISOString(),
    source_url: page.url(),
    authenticated: true,
    sample_only: true,
  }));
  if (!records.length || records.some(row => !row.location_text || !row.amount_text)) {
    throw new Error("DXBI sample is empty or lacks expected sale columns");
  }
  if (!(await isAuthenticated(page))) throw new Error("DXBI session expired during sampling");
  fs.mkdirSync(outputDir, { recursive: true });
  const output = path.join(outputDir, `dxbi_sales_sample_${nowStamp()}.jsonl`);
  fs.writeFileSync(output, records.map(row => JSON.stringify(row)).join("\n") + "\n", { mode: 0o600, flag: "wx" });
  return { output, authenticated: true, sample_only: true, rows: records.length,
    with_detail_url: records.filter(row => row.detail_url).length,
    with_unit_number: records.filter(row => row.unit_number).length,
    with_registration_number: records.filter(row => row.dld_transaction_number).length };
}

if (require.main === module) run()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });

module.exports = { rowToRecord, findDxbPage, captureSalesSample };
