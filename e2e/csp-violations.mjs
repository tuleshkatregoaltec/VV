// Visits the main pages and reports Content-Security-Policy violations and render failures.
//
//   JAD_PASSWORD=... node csp-violations.mjs [baseUrl] [outDir]
//
// baseUrl defaults to a local `wrangler pages dev` on :8788. The password is read from the
// environment and never printed. When baseUrl is not the production origin, calls to the API are
// relayed through Node with the production Origin and CORS headers added, so the page can load
// real data; the browser still evaluates the CSP against the original request URL.
import { mkdirSync } from 'node:fs'
import { chromium } from '@playwright/test'

const base = (process.argv[2] ?? 'http://localhost:8788').replace(/\/$/, '')
const outDir = process.argv[3] ?? '/tmp/csp-check'
const API = 'https://api-pilot.vitevue.com'
const PROD_ORIGIN = 'https://vitevue.com'
const email = process.env.JAD_EMAIL ?? 'jad@demo.com'
const password = process.env.JAD_PASSWORD
if (!password) throw new Error('Set JAD_PASSWORD')
mkdirSync(outDir, { recursive: true })

const PUBLIC_PAGES = ['/', '/auth']
const SIGNED_IN_PAGES = [
	'/dashboard',
	'/transactions/sales',
	'/analytics',
	'/radar',
	'/listings',
	'/upcoming',
	'/feasibility',
	'/chat',
	'/crm',
	'/crm/owners',
	'/crm/inbox',
	'/crm/whatsapp'
]

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
let currentPage = ''
const violations = new Map() // page -> Set
const consoleIssues = new Map()
const note = (map, page, text) => {
	if (!map.has(page)) map.set(page, new Set())
	map.get(page).add(text)
}

await context.addInitScript(() => {
	window.__csp = []
	document.addEventListener('securitypolicyviolation', (e) => {
		window.__csp.push(`${e.violatedDirective} blocked ${e.blockedURI || '(inline)'} @ ${e.sourceFile || ''}:${e.lineNumber || ''}`)
	})
})

if (base !== PROD_ORIGIN) {
	const cors = (origin) => ({
		'access-control-allow-origin': origin,
		'access-control-allow-credentials': 'true',
		'access-control-allow-headers': '*',
		'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
		vary: 'origin'
	})
	await context.route(`${API}/**`, async (route) => {
		const request = route.request()
		const origin = request.headers().origin ?? base
		if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors(origin) })
		try {
			const response = await context.request.fetch(request.url(), {
				method: request.method(),
				headers: { ...request.headers(), origin: PROD_ORIGIN },
				data: request.postDataBuffer() ?? undefined,
				failOnStatusCode: false
			})
			const headers = { ...response.headers(), ...cors(origin) }
			delete headers['content-encoding']
			delete headers['content-length']
			return route.fulfill({ status: response.status(), headers, body: await response.body() })
		} catch {
			return route.abort()
		}
	})
}

const page = await context.newPage()
page.on('console', (message) => {
	const text = message.text()
	if (/Content Security Policy|Refused to|violat/i.test(text)) note(violations, currentPage, `console: ${text.slice(0, 220)}`)
	else if (message.type() === 'error') note(consoleIssues, currentPage, text.slice(0, 160))
})
page.on('requestfailed', (request) =>
	note(consoleIssues, currentPage, `request failed: ${request.method()} ${request.url().slice(0, 120)} ${request.failure()?.errorText ?? ''}`)
)
page.on('response', (response) => {
	if (response.status() >= 400) note(consoleIssues, currentPage, `HTTP ${response.status()} ${response.url().slice(0, 120)}`)
})
page.on('pageerror', (error) => note(consoleIssues, currentPage, `pageerror: ${error.message.slice(0, 160)}`))

async function visit(path) {
	currentPage = path
	await page.goto(base + path, { waitUntil: 'domcontentloaded' })
	await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {})
	await page.waitForTimeout(3500)
	for (const entry of await page.evaluate(() => window.__csp ?? [])) note(violations, path, entry)
	const state = await page.evaluate(() => ({
		url: location.pathname,
		text: document.body.innerText.trim().length,
		canvas: document.querySelectorAll('canvas.maplibregl-canvas').length,
		error: /^\s*(404|500)\b/m.test(document.body.innerText) && document.body.innerText.length < 400
	}))
	if (path === '/crm/whatsapp') {
		const sdk = await page.evaluate(() => typeof window.FB)
		console.log(`facebook sdk on /crm/whatsapp: ${sdk}`)
	}
	await page.screenshot({ path: `${outDir}/${path.replace(/\//g, '_') || '_root'}.png` })
	return state
}

const results = []

// Positive control: the listener must see a violation when one really happens.
currentPage = 'control'
await page.goto(`${base}/auth`, { waitUntil: 'domcontentloaded' })
const control = await page.evaluate(async () => {
	await fetch('https://csp-control.example.invalid/').catch(() => {})
	await new Promise((resolve) => setTimeout(resolve, 200))
	return window.__csp
})
console.log(`control (expects 1+ violation): ${control.length}`)
if (control.length === 0) throw new Error('CSP listener did not fire on the control request')
for (const path of PUBLIC_PAGES) results.push([path, await visit(path)])

// Sign in through the real form.
currentPage = 'login'
await page.goto(`${base}/auth`, { waitUntil: 'domcontentloaded' })
await page.locator('input[type="email"]').first().fill(email)
await page.locator('input[type="password"]').first().fill(password)
await page.locator('button[type="submit"]').first().click()
await page.waitForURL((url) => !url.pathname.startsWith('/auth'), { timeout: 30000 })

for (const path of SIGNED_IN_PAGES) results.push([path, await visit(path)])

let failed = 0
console.log(`base: ${base}`)
for (const [path, state] of results) {
	const v = [...(violations.get(path) ?? [])]
	const ok = v.length === 0 && state.text > 40 && !state.error
	if (!ok) failed += 1
	console.log(`${ok ? 'PASS' : 'FAIL'} ${path} -> ${state.url} text=${state.text} map=${state.canvas} violations=${v.length}`)
	for (const line of v) console.log(`    CSP ${line}`)
}
const loginViolations = [...(violations.get('login') ?? [])]
for (const line of loginViolations) { failed += 1; console.log(`FAIL login CSP ${line}`) }
console.log('--- console errors (informational) ---')
for (const [path, set] of consoleIssues) for (const line of set) console.log(`${path}: ${line}`)
console.log(`TOTAL CSP violations: ${[...violations].filter(([k]) => k !== 'control').reduce((n, [, s]) => n + s.size, 0)}; failed pages: ${failed}`)
await browser.close()
process.exit(failed ? 1 : 0)
