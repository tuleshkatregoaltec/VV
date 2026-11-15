import { readFileSync } from 'node:fs'
import { render } from 'svelte/server'
import { describe, expect, it } from 'vitest'
import ListingSnapshotNotice from '$lib/components/listings/ListingSnapshotNotice.svelte'
import NewsCard from '$lib/components/news/NewsCard.svelte'
import NewsFreshnessNote from '$lib/components/news/NewsFreshnessNote.svelte'

const NOW = new Date('2026-11-15T09:00:00Z')
const article = (url: string) => ({
	id: 1,
	headline: 'Headline',
	url,
	publish_date: '2026-07-05T00:00:00Z',
	thumbnail_url: '',
	thumbnail_base64: null
})

describe('listings snapshot notice', () => {
	it('shows the snapshot date and how old it is', () => {
		const { body } = render(ListingSnapshotNotice, {
			props: { snapshotAt: '2026-05-27T08:00:00Z', now: NOW }
		})
		expect(body).toContain('27 May 2026')
		expect(body).toContain('5 months ago')
	})

	it('says prices and availability are not confirmed as current when the snapshot is old', () => {
		const { body } = render(ListingSnapshotNotice, {
			props: { snapshotAt: '2026-05-27T08:00:00Z', now: NOW }
		})
		expect(body).toMatch(/availability/i)
		expect(body).toMatch(/not\s+(been\s+)?(confirmed|verified)/i)
	})

	it('still tells the viewer the date is unknown when the capture date is missing', () => {
		const { body } = render(ListingSnapshotNotice, { props: { snapshotAt: null, now: NOW } })
		expect(body).toMatch(/capture date (is )?unavailable/i)
	})
})

describe('news freshness', () => {
	it('shows the newest article date and flags an old feed', () => {
		const { body } = render(NewsFreshnessNote, {
			props: { newestPublishedAt: '2026-07-05T00:00:00Z', now: NOW }
		})
		expect(body).toContain('5 Jul 2026')
		expect(body).toMatch(/not updating|paused|no newer/i)
	})

	it('renders nothing alarming for a fresh feed', () => {
		const { body } = render(NewsFreshnessNote, {
			props: { newestPublishedAt: '2026-11-14T00:00:00Z', now: NOW }
		})
		expect(body).not.toMatch(/not updating|paused|no newer/i)
	})
})

describe('NewsCard link safety', () => {
	it('keeps an https article link', () => {
		const { body } = render(NewsCard, { props: { article: article('https://example.com/a') } })
		expect(body).toContain('href="https://example.com/a"')
	})

	it('drops a javascript: article link instead of rendering it as an href', () => {
		const { body } = render(NewsCard, { props: { article: article('javascript:alert(1)') } })
		expect(body.toLowerCase()).not.toContain('javascript:')
	})
})

describe('listings page wiring', () => {
	const page = readFileSync('src/routes/listings/+page.svelte', 'utf8')

	it('renders the snapshot notice and labels the new-listings tile against it', () => {
		expect(page).toContain('<ListingSnapshotNotice')
		expect(page).toContain('newListingsLabel(snapshotAt)')
		expect(page).not.toMatch(/>New in 30 days</)
	})

	it('offers no phone or email links and never puts a raw scraped URL in an href', () => {
		expect(page).not.toMatch(/tel:|mailto:/)
		expect(page).not.toMatch(/href=\{selectedListing\.share_url\}/)
	})
})
