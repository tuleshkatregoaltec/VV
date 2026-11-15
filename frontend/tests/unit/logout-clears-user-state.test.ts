import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { authClient, logout } from '../../src/lib/api/auth'
import {
	clearUserBrowserState,
	USER_LOCAL_STORAGE_KEYS
} from '../../src/lib/auth/user-browser-state'

vi.mock('../../src/lib/stores/user.svelte', () => ({ clearUser: vi.fn() }))

class MemoryStorage {
	private data = new Map<string, string>()
	get length() {
		return this.data.size
	}
	key(index: number) {
		return [...this.data.keys()][index] ?? null
	}
	getItem(key: string) {
		return this.data.get(key) ?? null
	}
	setItem(key: string, value: string) {
		this.data.set(key, String(value))
	}
	removeItem(key: string) {
		this.data.delete(key)
	}
	clear() {
		this.data.clear()
	}
}

const asStorage = (s: MemoryStorage) => s as unknown as Storage

describe('clearUserBrowserState removes per-user data from the browser', () => {
	it('removes every user-scoped key and chat selections, and keeps unrelated keys', () => {
		const local = new MemoryStorage()
		const session = new MemoryStorage()
		for (const key of [
			'vitevue-preferences',
			'vitevue-dashboard-kpi-cards',
			'vitevue-workflow-cards',
			'filter-propertyType',
			'filter-timeframe'
		])
			local.setItem(key, '"x"')
		local.setItem('unrelated-site-setting', '1')
		session.setItem('chat:conversation:org-1:user-2', '41')
		session.setItem('chat:conversation:org-9:user-8', '7')
		session.setItem('selected_tier', 'tier1')
		session.setItem('unrelated', '1')

		clearUserBrowserState(asStorage(local), asStorage(session))

		for (const key of USER_LOCAL_STORAGE_KEYS) expect(local.getItem(key)).toBeNull()
		expect(local.getItem('unrelated-site-setting')).toBe('1')
		expect(session.getItem('chat:conversation:org-1:user-2')).toBeNull()
		expect(session.getItem('chat:conversation:org-9:user-8')).toBeNull()
		expect(session.getItem('selected_tier')).toBeNull()
		expect(session.getItem('unrelated')).toBe('1')
	})

	it('lists the keys the app actually writes', () => {
		expect([...USER_LOCAL_STORAGE_KEYS].sort()).toEqual([
			'filter-propertyType',
			'filter-timeframe',
			'vitevue-dashboard-kpi-cards',
			'vitevue-preferences',
			'vitevue-workflow-cards'
		])
	})

	it('survives storage that throws', () => {
		const broken = {
			get length(): number {
				throw new Error('blocked')
			},
			key() {
				throw new Error('blocked')
			},
			removeItem() {
				throw new Error('blocked')
			}
		} as unknown as Storage
		expect(() => clearUserBrowserState(broken, broken)).not.toThrow()
	})
})

describe('logout', () => {
	const local = new MemoryStorage()
	const session = new MemoryStorage()
	beforeEach(() => {
		local.clear()
		session.clear()
		vi.stubGlobal('localStorage', local)
		vi.stubGlobal('sessionStorage', session)
		vi.stubGlobal('window', { location: { href: '' } })
	})
	afterEach(() => {
		vi.unstubAllGlobals()
		vi.restoreAllMocks()
	})

	it('wipes per-user storage even when Supabase sign-out fails', async () => {
		vi.spyOn(authClient, 'signOut').mockRejectedValue(new Error('network'))
		vi.spyOn(console, 'error').mockImplementation(() => {})
		local.setItem('vitevue-preferences', '{"theme":"dark"}')
		local.setItem('vitevue-dashboard-kpi-cards', '["a"]')
		session.setItem('chat:conversation:org:user', '5')

		await logout('/auth')

		expect(local.getItem('vitevue-preferences')).toBeNull()
		expect(local.getItem('vitevue-dashboard-kpi-cards')).toBeNull()
		expect(session.getItem('chat:conversation:org:user')).toBeNull()
		expect((globalThis as unknown as { window: Window }).window.location.href).toBe('/auth')
	})
})
