const SVG_NS = 'http://www.w3.org/2000/svg'

function svgElement(name: string, attributes: Record<string, string>): SVGElement {
	const element = document.createElementNS(SVG_NS, name)
	for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value)
	return element
}

/** Teardrop pin for a building or land point. Built from DOM nodes so no markup string is parsed. */
export function createPinSvg(fill: string): SVGElement {
	const svg = svgElement('svg', {
		width: '28',
		height: '36',
		viewBox: '0 0 28 36',
		fill: 'none'
	})
	svg.append(
		svgElement('path', {
			d: 'M14 0C6.268 0 0 6.268 0 14C0 24.5 14 36 14 36C14 36 28 24.5 28 14C28 6.268 21.732 0 14 0Z',
			fill
		}),
		svgElement('circle', { cx: '14', cy: '14', r: '6', fill: 'white' })
	)
	return svg
}

/** Round marker glyph for the selected project. */
export function createProjectDotSvg(): SVGElement {
	const svg = svgElement('svg', {
		class: 'w-5 h-5 text-white',
		fill: 'currentColor',
		viewBox: '0 0 20 20'
	})
	svg.append(
		svgElement('path', {
			'fill-rule': 'evenodd',
			d: 'M10 18a8 8 0 100-16 8 8 0 000 16z',
			'clip-rule': 'evenodd'
		})
	)
	return svg
}
