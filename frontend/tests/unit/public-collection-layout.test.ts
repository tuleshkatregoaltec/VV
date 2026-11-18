import { beforeEach, describe, expect, it, vi } from 'vitest'

const posthogMock = vi.hoisted(() => ({
	__loaded: false,
	init: vi.fn(),
	opt_out_capturing: vi.fn()
}))

vi.mock('posthog-js', () => ({ default: posthogMock }))
vi.mock('$app/environment', () => ({ browser: true }))
vi.mock('$env/dynamic/public', () => ({
	env: { PUBLIC_POSTHOG_KEY: 'phc_key', PUBLIC_POSTHOG_HOST: 'https://ph.example' }
}))
vi.mock('$lib/queries/client', () => ({ getQueryClient: () => ({}) }))
vi.mock('$lib/stores/user.svelte', () => ({ getCurrentUser: vi.fn(async () => null) }))

import { load } from '../../src/routes/+layout'

const run = (pathname: string) =>
	(load as (e: unknown) => Promise<unknown>)({ url: new URL(`https://app.test${pathname}`) })

describe('root layout load and analytics', () => {
	beforeEach(() => {
		posthogMock.__loaded = false
		posthogMock.init.mockClear()
		posthogMock.opt_out_capturing.mockClear()
	})

	it('does not init posthog on /collections/*', async () => {
		await run('/collections/tok')
		expect(posthogMock.init).not.toHaveBeenCalled()
	})

	it('opts out when posthog was already loaded earlier in the tab', async () => {
		posthogMock.__loaded = true
		await run('/collections/tok')
		expect(posthogMock.opt_out_capturing).toHaveBeenCalledOnce()
	})

	it('still inits posthog on other pages', async () => {
		await run('/')
		expect(posthogMock.init).toHaveBeenCalledOnce()
		expect(posthogMock.opt_out_capturing).not.toHaveBeenCalled()
	})
})
