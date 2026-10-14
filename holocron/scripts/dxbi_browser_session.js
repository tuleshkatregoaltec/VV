const fs = require("node:fs");
const path = require("node:path");

function browserEndpoint(env = process.env) {
  if (env.DXBI_SALES_CDP_ENDPOINT) return env.DXBI_SALES_CDP_ENDPOINT;
  if (env.DXBI_BROWSER_USER_DATA_DIR) {
    const [port, endpoint] = fs.readFileSync(
      path.join(env.DXBI_BROWSER_USER_DATA_DIR, "DevToolsActivePort"), "utf8",
    ).trim().split(/\r?\n/);
    if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535 ||
        !endpoint?.startsWith("/devtools/browser/")) {
      throw new Error("Invalid browser debugging endpoint");
    }
    return `ws://127.0.0.1:${port}${endpoint}`;
  }
  return "http://127.0.0.1:9222";
}

function loadCredentials(env = process.env) {
  const email = env.DXBI_EMAIL || env.DXBI_USERNAME;
  const password = env.DXBI_PASSWORD;
  if (email || password) {
    if (!email || !password) throw new Error("Both DXBI email and password are required");
    return { email, password };
  }
  if (!env.DXBI_CREDENTIALS_PATH) return null;
  let value;
  try {
    value = JSON.parse(fs.readFileSync(env.DXBI_CREDENTIALS_PATH, "utf8"));
  } catch {
    throw new Error("DXBI credentials file could not be read as JSON");
  }
  if (!value || typeof value.email !== "string" || !value.email.trim() ||
      typeof value.password !== "string" || !value.password) {
    throw new Error("DXBI credentials file must contain email and password");
  }
  return { email: value.email, password: value.password };
}

function isDxbiUrl(url) {
  try {
    return new URL(url).origin === "https://dxbinteract.com";
  } catch {
    return false;
  }
}

async function isAuthenticated(page) {
  if (!isDxbiUrl(page.url())) return false;
  return page.evaluate(() => document.querySelector("#G_USER_AUTH")?.value === "Y");
}

async function ensureAuthenticated(page, reason = "session check", env = process.env) {
  if (!isDxbiUrl(page.url())) throw new Error("DXBI authentication requires the trusted DXBI origin");
  if (await isAuthenticated(page)) return;
  const credentials = loadCredentials(env);
  if (!credentials) throw new Error(`${reason}: DXBI is not authenticated; sign in to the attached browser or configure DXBI credentials`);
  const signIn = page.locator("a.LogIn:visible");
  if (await signIn.count() === 1) await signIn.click();

  // The login is an APEX dialog, not the publicly accessible sales report.
  // Wait for a unique visible password form on the exact trusted origin.
  let form;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const frames = page.frames().filter(frame => isDxbiUrl(frame.url()));
    const candidates = [];
    for (const frame of frames) {
      const password = frame.locator("input[type=password]:visible");
      if (await password.count() === 1) candidates.push(frame);
    }
    if (candidates.length === 1) { form = candidates[0]; break; }
    if (candidates.length > 1) throw new Error("Ambiguous DXBI login forms; credentials were not submitted");
    await page.waitForTimeout(1000);
  }
  if (!form) throw new Error("DXBI login form unavailable; complete browser security verification before retrying");
  const username = form.locator("input[type=email]:visible, input[autocomplete=username]:visible, input[id$=_USERNAME]:visible, input[id$=_EMAIL]:visible");
  const submit = form.getByRole("button", { name: /^(sign in|log in|login)$/i });
  if (await username.count() !== 1 || await submit.count() !== 1) {
    throw new Error("Unrecognized DXBI login form; credentials were not submitted");
  }
  // Do not emit Playwright locator errors, which can include the submitted value.
  try {
    await username.fill(credentials.email);
    await form.locator("input[type=password]:visible").fill(credentials.password);
    await submit.click();
  } catch {
    throw new Error("DXBI credential submission failed");
  }
  try {
    await page.waitForFunction(() => document.querySelector("#G_USER_AUTH")?.value === "Y", null, { timeout: 30000 });
  } catch {
    throw new Error("DXBI did not confirm authentication; no authenticated scrape was started");
  }
  if (!(await isAuthenticated(page))) throw new Error("DXBI authentication could not be verified");
}

module.exports = { browserEndpoint, loadCredentials, isDxbiUrl, isAuthenticated, ensureAuthenticated };
