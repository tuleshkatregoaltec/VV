/** Decisions behind the collections UI, kept free of Svelte so they can be unit-tested. */
import type { CompanyListingCompany } from '$lib/crm/api/types'

export const MAX_COLLECTION_ITEMS = 50

export const countLabel = (n: number) => `${n} / ${MAX_COLLECTION_ITEMS}`

export const isCollectionFull = (itemCount: number) => itemCount >= MAX_COLLECTION_ITEMS

/**
 * Company cards carry no `managed` flag. They belong to the organization's connected company when
 * the browsed company is the matching one; the server enforces eligibility regardless.
 */
export function canAddToCollection(data?: {
	company?: Pick<CompanyListingCompany, 'broker_id'> | null
	matching_company?: Pick<CompanyListingCompany, 'broker_id'> | null
}): boolean {
	const a = data?.company?.broker_id
	const b = data?.matching_company?.broker_id
	return Boolean(a && b && a === b)
}

export interface MenuItemState {
	checked: boolean
	disabled: boolean
	hint: string | null
}

/** One collection in the Add-to-collection menu. A full collection is disabled with "50 / 50". */
export function menuItemState(c: { item_count: number }, contains: boolean): MenuItemState {
	if (contains) return { checked: true, disabled: true, hint: null }
	const full = isCollectionFull(c.item_count)
	return { checked: false, disabled: full, hint: full ? countLabel(c.item_count) : null }
}

/** The button is a sibling of the card's clickable element; its click must not reach the card. */
export function addButtonClick(e: Event, toggle: () => void) {
	e.stopPropagation()
	toggle()
}

export interface MenuRowState extends MenuItemState {
	/** The collection's items have not loaded yet: membership is unknown, so the row is not clickable. */
	pending: boolean
}

/** A menu row from the collection's live detail (undefined while loading). */
export function menuRowState(
	c: { item_count: number },
	detail: { items: { listing_key: string }[] } | undefined,
	listingKey: string
): MenuRowState {
	if (!detail) return { checked: false, disabled: true, hint: null, pending: true }
	return {
		...menuItemState(
			c,
			detail.items.some((i) => i.listing_key === listingKey)
		),
		pending: false
	}
}
