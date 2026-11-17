import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinSvg, createProjectDotSvg } from '../../src/lib/components/map/markerElements'

class FakeElement {
	children: FakeElement[] = []
	attributes: Record<string, string> = {}
	constructor(public name: string) {}
	setAttribute(key: string, value: string) {
		this.attributes[key] = value
	}
	append(...nodes: FakeElement[]) {
		this.children.push(...nodes)
	}
}

afterEach(() => vi.unstubAllGlobals())

describe('map marker elements are built from DOM nodes', () => {
	it('colours the pin with the given fill and never parses markup', () => {
		vi.stubGlobal('document', {
			createElementNS: (_ns: string, name: string) => new FakeElement(name)
		})
		const evil = '"/><script>alert(1)</script>'
		const svg = createPinSvg(evil) as unknown as FakeElement
		expect(svg.name).toBe('svg')
		expect(svg.children.map((child) => child.name)).toEqual(['path', 'circle'])
		expect(svg.children[0].attributes.fill).toBe(evil)
		expect(createProjectDotSvg()).toBeDefined()
	})
})
