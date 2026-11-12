import { render } from 'svelte/server'
import { describe, expect, it } from 'vitest'
import PhotoSlider from '$lib/collections/PhotoSlider.svelte'

// Server render (no DOM env): checks what an agent/client sees before any interaction.
describe('PhotoSlider', () => {
	it('shows every photo with navigation when a listing has several', () => {
		const photos = ['https://p/1.jpg', 'https://p/2.jpg', 'https://p/3.jpg']
		const html = render(PhotoSlider, { props: { photos } }).body
		for (const src of photos) expect(html).toContain(src)
		expect(html).toContain('1 / 3')
		expect(html).toContain('Next photo')
		expect(html).toContain('Previous photo')
	})

	it('shows no arrows or counter for a single photo', () => {
		const html = render(PhotoSlider, { props: { photos: ['https://p/1.jpg'] } }).body
		expect(html).toContain('https://p/1.jpg')
		expect(html).not.toContain('Next photo')
		expect(html).not.toContain('1 / 1')
	})

	it('shows the empty label instead of a broken image when there are no photos', () => {
		const html = render(PhotoSlider, { props: { photos: [], empty: 'No longer available' } }).body
		expect(html).toContain('No longer available')
		expect(html).not.toContain('<img')
	})
})

describe('PhotoSlider inside a clickable card', () => {
	// The company listing card is a <button>; a nested button is invalid HTML and would
	// swallow the card's click, so the slider must render no buttons there.
	it('renders no arrow buttons with controls off, but still shows every photo and the counter', () => {
		const photos = ['https://p/1.jpg', 'https://p/2.jpg']
		const html = render(PhotoSlider, { props: { photos, controls: false } }).body
		expect(html).not.toContain('<button')
		for (const src of photos) expect(html).toContain(src)
		expect(html).toContain('1 / 2')
	})
})
