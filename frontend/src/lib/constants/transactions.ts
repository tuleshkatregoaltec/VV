// Property usage types
export const PROPERTY_USAGE = {
	RESIDENTIAL: 'Residential',
	COMMERCIAL: 'Commercial'
} as const;

// Column definitions for transactions table
const baseColumns = [
	{ id: 'date', label: 'Date', align: 'left' as const },
	{ id: 'area_name', label: 'Area', align: 'left' as const},
	{ id: 'project', label: 'Project', align: 'left' as const },
	{ id: 'building', label: 'Building', align: 'left' as const },
	{ id: 'propertyType', label: 'Property Type', align: 'left' as const },
];

export const RESIDENTIAL_COLUMNS = [
	...baseColumns,
	{ id: 'bedrooms', label: 'Bedrooms', align: 'left' as const, badge: true },
	{ id: 'area', label: 'Area (sq.m)', align: 'right' as const, format: (val: number) => val.toLocaleString() },
	{ id: 'price', label: 'Price (AED)', align: 'right' as const, format: (val: number) => val.toLocaleString() },
	{ id: 'pricePerSqM', label: 'Price/sq.m', align: 'right' as const, highlighted: true, format: (val: number) => val.toLocaleString() },
	{ id: 'registration', label: 'Registration', align: 'left' as const }
];

export const COMMERCIAL_COLUMNS = [
	...baseColumns,
	{ id: 'propertySubType', label: 'Sub Type', align: 'left' as const },
	{ id: 'area', label: 'Area (sq.m)', align: 'right' as const, format: (val: number) => val.toLocaleString() },
	{ id: 'price', label: 'Price (AED)', align: 'right' as const, format: (val: number) => val.toLocaleString() },
	{ id: 'pricePerSqM', label: 'Price/sq.m', align: 'right' as const, highlighted: true, format: (val: number) => val.toLocaleString() },
	{ id: 'registration', label: 'Registration', align: 'left' as const }
];

// Timeframe to days conversion
export const TIMEFRAME_MAPPING: Record<string, number> = {
	'Last Week': 7,
	'Last Month': 30,
	'Last 3 Months': 90,
	'Last 6 Months': 180,
	'Last Year': 365
};

// Pagination
export const DEFAULT_ITEMS_PER_PAGE = 30;
export const MAX_VISIBLE_PAGES = 7;
