// Signs in on the live site, opens the Owners page and reports any "busy" text.
//   VV_LOGIN_FILE=~/.config/vv-deploy/vitevue-login-passwords-2026-11-11.txt \
//     node e2e/tools/owners-busy-check.mjs maan@demo.com [outDir] [baseUrl]
// The login file is tab-separated "email<TAB>password"; the password is never printed.
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { chromium } from '@playwright/test'

const [email, outDir = '.', baseUrl = 'https://vitevue.com'] = process.argv.slice(2)
const file = process.env.VV_LOGIN_FILE.replace(/^~/, homedir())
const password = Object.fromEntries(
	readFileSync(file, 'utf8')
		.split('\n')
		.filter((line) => line.includes('\t'))
		.map((line) => line.split('\t'))
)[email]

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const crm = []
let inflight = 0
const isCrm = (r) => r.url().includes('/api/v1/crm/')
page.on('request', (r) => {
	if (isCrm(r)) inflight++
})
page.on('requestfailed', (r) => {
	if (isCrm(r)) inflight--
})
page.on('response', (r) => {
	if (isCrm(r.request())) {
		inflight--
		crm.push(r.status())
	}
})
await page.goto(`${baseUrl}/auth?next=/crm/owners`)
await page.getByLabel('Email').fill(email)
await page.getByLabel('Password').fill(password)
await page.locator('form button[type="submit"]').click()
await page.waitForURL((url) => !url.pathname.startsWith('/auth'), { timeout: 60_000 })
if (!page.url().includes('/crm/owners')) await page.goto(`${baseUrl}/crm/owners`)
// Panels retry, so watch until CRM traffic has been quiet for 8 s (at most 2 min) and
// record the most "busy" elements seen at any moment, not only at the end.
let busy = 0
let quiet = 0
for (let second = 0; second < 120 && quiet < 8; second++) {
	await page.waitForTimeout(1000)
	busy = Math.max(busy, await page.getByText(/busy/i).count())
	quiet = inflight > 0 ? 0 : quiet + 1
}
const shot = join(outDir, 'owners-busy-check.png')
await page.screenshot({ path: shot, fullPage: true })
const tally = crm.reduce((acc, s) => ({ ...acc, [s]: (acc[s] ?? 0) + 1 }), {})
console.log(`url=${page.url()}`)
console.log(`crm responses=${JSON.stringify(tally)}`)
console.log(`elements containing "busy": ${busy}`)
console.log(`screenshot=${shot}`)
await browser.close()
process.exit(busy ? 1 : 0)
