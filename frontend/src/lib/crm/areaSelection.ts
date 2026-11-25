/** "My areas" selection: an all-areas switch and a name search over the available areas. */

/** Areas whose name contains the search text (case-insensitive); empty search shows all. */
export function matchingAreas<T extends { area: string }>(list: T[], search: string): T[] {
	const term = search.trim().toLocaleLowerCase()
	return term ? list.filter((item) => item.area.toLocaleLowerCase().includes(term)) : list
}

/** True when every available area is selected (and there is at least one). */
export function allSelected(available: string[], selected: ReadonlySet<string>): boolean {
	return available.length > 0 && available.every((area) => selected.has(area))
}

/**
 * Select or clear every available area. Searching never narrows this: "All areas" means all of
 * them, including those the current search hides.
 */
export function setAll(
	available: string[],
	selected: ReadonlySet<string>,
	on: boolean
): Set<string> {
	const next = new Set(selected)
	for (const area of available) {
		if (on) next.add(area)
		else next.delete(area)
	}
	return next
}
