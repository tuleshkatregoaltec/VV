const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { chromium } = require("../../e2e/node_modules/playwright");
const { browserEndpoint, loadCredentials, ensureAuthenticated } = require("../scripts/dxbi_browser_session");
const { rowToRecord, captureSalesSample } = require("../scripts/dxbi_sales_dynamic_bucket_runner");

test("endpoint discovery uses saved permission without exposing other profile data", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dxbi-debug-"));
  try {
    fs.writeFileSync(path.join(dir, "DevToolsActivePort"), "9222\r\n/devtools/browser/test\r\n");
    assert.equal(browserEndpoint({ DXBI_BROWSER_USER_DATA_DIR: dir }), "ws://127.0.0.1:9222/devtools/browser/test");
    fs.writeFileSync(path.join(dir, "DevToolsActivePort"), "99999\n/invalid");
    assert.throws(() => browserEndpoint({ DXBI_BROWSER_USER_DATA_DIR: dir }), /Invalid/);
  } finally { fs.rmSync(dir, { recursive: true }); }
});

test("partial credentials fail instead of silently selecting another account", () => {
  assert.throws(() => loadCredentials({ DXBI_EMAIL: "test@example.com" }), /Both/);
  assert.equal(loadCredentials({}), null);
});

test("malformed credential files cannot leak their contents in parse errors", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dxbi-credentials-"));
  try {
    const file = path.join(dir, "credentials.json");
    fs.writeFileSync(file, '{"password":"fixture-secret"', { mode: 0o600 });
    assert.throws(() => loadCredentials({ DXBI_CREDENTIALS_PATH: file }), error =>
      error.message === "DXBI credentials file could not be read as JSON");
  } finally { fs.rmSync(dir, { recursive: true }); }
});

test("provider property tokens cannot become DLD registration numbers", () => {
  const row = { columns: [{ id: "DETAIL_LINK", links: [{ href: "https://dxbinteract.com/sold/t-opaque" }] }] };
  assert.equal(rowToRecord({ bucket: {}, row }).dld_transaction_number, "");
  row.columns.push({ id: "TRANSACTION_NUMBER", text: "11-123-2026" });
  assert.equal(rowToRecord({ bucket: {}, row }).dld_transaction_number, "11-123-2026");
});

test("authentication and bounded sampling respect account and origin boundaries", async t => {
  const browser = await chromium.launch({ headless: true });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dxbi-sample-"));
  try {
    await t.test("a public report never proves authentication", async () => {
      const page = await browser.newPage();
      await page.route("https://dxbinteract.com/", r => r.fulfill({ contentType: "text/html", body: '<div id="report_soldhistory"></div><input id="G_USER_AUTH" value="N">' }));
      await page.goto("https://dxbinteract.com/");
      await assert.rejects(ensureAuthenticated(page, "test", {}), /not authenticated/);
      await page.close();
    });
    await t.test("credentials are never submitted to a lookalike origin", async () => {
      const page = await browser.newPage();
      await page.route("https://dxbinteract.com.invalid/", r => r.fulfill({ contentType: "text/html", body: '<input id="G_USER_AUTH" value="Y">' }));
      await page.goto("https://dxbinteract.com.invalid/");
      await assert.rejects(ensureAuthenticated(page, "test", { DXBI_EMAIL: "test@example.com", DXBI_PASSWORD: "fixture-secret" }), /trusted/);
      await page.close();
    });
    await t.test("APEX dialog login must confirm authentication on the parent", async () => {
      const page = await browser.newPage();
      await page.route("https://dxbinteract.com/", r => r.fulfill({ contentType: "text/html", body: '<input id="G_USER_AUTH" value="N"><iframe src="/login"></iframe>' }));
      await page.route("https://dxbinteract.com/login", r => r.fulfill({ contentType: "text/html", body: '<input type="email"><input type="password"><button onclick="parent.document.querySelector(\'#G_USER_AUTH\').value=\'Y\'">Sign In</button>' }));
      await page.goto("https://dxbinteract.com/");
      await ensureAuthenticated(page, "test", { DXBI_EMAIL: "test@example.com", DXBI_PASSWORD: "fixture-secret" });
      assert.equal(await page.locator("#G_USER_AUTH").inputValue(), "Y");
      await page.close();
    });
    await t.test("an authenticated sample preserves source fields and never claims a completed backfill", async () => {
      const page = await browser.newPage();
      const row = '<tr><td headers="PATH_NAME"><a href="/sold/t-opaque">Tower, Area Ready Apartment, No. 101</a></td><td headers="TOTAL_PRICE">AED 1,000,000</td></tr>';
      const noLink = row.replace('/sold/t-opaque', 'javascript:void(0)');
      await page.route("https://dxbinteract.com/", r => r.fulfill({ contentType: "text/html", body: '<input id="G_USER_AUTH" value="Y"><table id="report_table_soldhistory"><tbody>' + noLink + row.repeat(20) + '</tbody></table>' }));
      await page.goto("https://dxbinteract.com/");
      // No configured credentials are needed when the profile is already authenticated.
      await ensureAuthenticated(page, "test", {});
      const result = await captureSalesSample(page, dir);
      assert.equal(result.rows, 13);
      assert.equal(result.with_registration_number, 0);
      assert.equal(result.with_detail_url, 12); // A real sale with no public detail link is retained.
      const records = fs.readFileSync(result.output, "utf8").trim().split("\n").map(JSON.parse);
      assert.ok(records.every(r => r.sample_only && r.unit_number === "101" && r.dld_transaction_number === ""));
      assert.deepEqual(fs.readdirSync(dir), [path.basename(result.output)]);
      await page.close();
    });
  } finally {
    await browser.close();
    fs.rmSync(dir, { recursive: true });
  }
});

test("compact scrape preserves the explicit property title and hidden units never become building numbers", () => {
  const record = rowToRecord({ bucket: {}, row: { columns: [
    { id: 'PATH_NAME', text: "Buyer's agent Person Building No. 12, Area Ready Apartment, No. u-hidden", location_titles: ['02 Residence, Area'], links: [] },
  ] } });
  assert.equal(record.location_title, '02 Residence, Area');
  assert.equal(record.unit_number, '');
  assert.match(record.location_text, /Person/); // Original evidence remains available.
});
