// Property usage. DXBI records carry a property type but no usage: the backend groups the types
// (apartments, villas, townhouses, hotel apartments are Residential; offices, shops, warehouses
// and other business premises are Commercial). Plots and untyped records appear under All only.
export const PROPERTY_USAGE = {
	RESIDENTIAL: 'Residential',
	COMMERCIAL: 'Commercial',
	ALL: 'All'
} as const

export const PROPERTY_USAGE_OPTIONS = [
	PROPERTY_USAGE.RESIDENTIAL,
	PROPERTY_USAGE.COMMERCIAL,
	PROPERTY_USAGE.ALL
]

// Column type definition
export type ColumnDefinition = {
	id: string
	label: string
	align?: 'left' | 'center' | 'right'
	format?: (value: any, row?: any) => string
	badge?: boolean
	highlighted?: boolean
	defaultVisible?: boolean // If false, column is hidden by default but can be toggled on
}

// Numbers are formatted the same way in every browser: the values come rounded from the API
// (sizes to 0.01 m², amounts and AED/m² to whole dirhams), so the page shows them exactly.
const aedFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const sqmFormat = new Intl.NumberFormat('en-US', {
	minimumFractionDigits: 2,
	maximumFractionDigits: 2
})
const monthsFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })

export function formatAed(value: number | null | undefined): string {
	return value == null ? '-' : aedFormat.format(value)
}

export function formatSqm(value: number | null | undefined): string {
	return value == null ? '-' : sqmFormat.format(value)
}

export function formatCount(value: number): string {
	return aedFormat.format(value)
}

function formatMonths(value: number | null | undefined): string {
	return value == null ? '-' : monthsFormat.format(value)
}

// DXBI sales (dxbi_sales_unit_events): one row per sale of one unit.
export const SALES_COLUMNS: ColumnDefinition[] = [
	{ id: 'date', label: 'Date', align: 'left', defaultVisible: true },
	{ id: 'unit', label: 'Unit', align: 'left', defaultVisible: true },
	{ id: 'building', label: 'Building', align: 'left', defaultVisible: true },
	{ id: 'location', label: 'Location', align: 'left', defaultVisible: true },
	{ id: 'project', label: 'Project', align: 'left', defaultVisible: false },
	{ id: 'propertyType', label: 'Property Type', align: 'left', defaultVisible: true },
	{ id: 'bedrooms', label: 'Bedrooms', align: 'left', badge: true, defaultVisible: true },
	{ id: 'size', label: 'Size (sq.m)', align: 'right', format: formatSqm, defaultVisible: true },
	{ id: 'price', label: 'Price (AED)', align: 'right', format: formatAed, defaultVisible: true },
	{
		id: 'pricePerSqM',
		label: 'Price/sq.m (AED)',
		align: 'right',
		highlighted: true,
		format: formatAed,
		defaultVisible: true
	},
	{ id: 'status', label: 'Status', align: 'left', defaultVisible: true }
]

// DXBI leases (dxbi_rental_events): one row per lease of one unit.
export const RENTAL_COLUMNS: ColumnDefinition[] = [
	{ id: 'startDate', label: 'Start Date', align: 'left', defaultVisible: true },
	{ id: 'endDate', label: 'End Date', align: 'left', defaultVisible: true },
	{ id: 'unit', label: 'Unit', align: 'left', defaultVisible: true },
	{ id: 'building', label: 'Building', align: 'left', defaultVisible: true },
	{ id: 'location', label: 'Location', align: 'left', defaultVisible: true },
	{ id: 'project', label: 'Project', align: 'left', defaultVisible: false },
	{ id: 'propertyType', label: 'Property Type', align: 'left', defaultVisible: true },
	{ id: 'bedrooms', label: 'Bedrooms', align: 'left', badge: true, defaultVisible: true },
	{ id: 'size', label: 'Size (sq.m)', align: 'right', format: formatSqm, defaultVisible: true },
	{
		id: 'annualRent',
		label: 'Annual Rent (AED)',
		align: 'right',
		highlighted: true,
		format: formatAed,
		defaultVisible: true
	},
	{
		id: 'contractAmount',
		label: 'Contract Amount (AED)',
		align: 'right',
		format: formatAed,
		defaultVisible: false
	},
	{
		id: 'termMonths',
		label: 'Term (months)',
		align: 'right',
		format: formatMonths,
		defaultVisible: false
	},
	{ id: 'contractType', label: 'Contract Type', align: 'left', defaultVisible: true }
]

// Timeframe to days conversion: the last N calendar days, today included.
export const TIMEFRAME_MAPPING: Record<string, number> = {
	'Last Week': 7,
	'Last Month': 30,
	'Last 3 Months': 90,
	'Last 6 Months': 180,
	'Last Year': 365
}

// Pagination
export const DEFAULT_ITEMS_PER_PAGE = 30
export const MAX_VISIBLE_PAGES = 7
