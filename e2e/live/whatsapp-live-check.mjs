// Unauthenticated live check of the deployed pilot: routes resolve (no 404) and the
// bundle contains the Connect WhatsApp page. Run from e2e/: node live/whatsapp-live-check.mjs
import { chromium } from "playwright";

const base = process.env.LIVE_BASE ?? "https://vv-pilot.pages.dev";
const browser = await chromium.launch();
const page = await browser.newPage();
const scripts = new Set();
page.on("response", (r) => {
	if (r.url().endsWith(".js")) scripts.add(r.url());
});
let failed = false;
for (const path of ["/crm/whatsapp", "/admin/whatsapp"]) {
	const response = await page.goto(base + path, { waitUntil: "networkidle" });
	await page.waitForTimeout(1500);
	const status = response?.status();
	const final = new URL(page.url()).pathname;
	const ok = status !== 404 && status !== undefined && status < 400;
	console.log(`${path}: HTTP ${status} -> ${final} ${ok ? "OK" : "FAIL"}`);
	failed ||= !ok;
}
let found = [];
for (const url of scripts) {
	const text = await (await fetch(url)).text();
	for (const marker of ["Connect WhatsApp", "signup/config", "api/v1/admin/whatsapp"]) {
		if (text.includes(marker)) found.push(`${marker} @ ${url.split("/").slice(-2).join("/")}`);
	}
}
console.log("bundle markers:", found.length ? found.slice(0, 6) : "NONE");
failed ||= found.length === 0;
await browser.close();
console.log(failed ? "RESULT: FAIL" : "RESULT: PASS");
process.exit(failed ? 1 : 0);
