/**
 * Market mode example data (UI only, 7 Oct). Copied from the v2 mockup (vitevue-crm-v2.html,
 * window.VV_MARKET; spec: market-mode-spec.md sections 3 and 6). Every dataset carries
 * src: 'demo' (Platform demo, Sep 2026) or 'ex' (Example). Nothing here is live data; each
 * screen is replaced by the platform's own endpoints when Market mode is wired up.
 */

export type Src = 'demo' | 'ex'
export type Status = 'Live' | 'Being fixed' | 'In build' | 'Not yet'

export const LABELS: Record<Src, string> = { demo: 'Platform demo, Sep 2026', ex: 'Example' }
export const AS_OF = '2026-10-06'

export interface MarketScreen {
	id: string
	path: string
	label: string
	grp: string
	status: Status
	tier: string
}

export const MARKET_SCREENS: MarketScreen[] = [
	{
		id: 'home',
		path: '/crm/market',
		label: 'Market home',
		grp: 'Market',
		status: 'Live',
		tier: 'Tier 1'
	},
	{
		id: 'tx',
		path: '/crm/market/transactions',
		label: 'Transactions',
		grp: 'Sales and rents',
		status: 'Live',
		tier: 'Tier 1'
	},
	{
		id: 'an',
		path: '/crm/market/analytics',
		label: 'Analytics',
		grp: 'Sales and rents',
		status: 'Live',
		tier: 'Tier 1'
	},
	{
		id: 'ls',
		path: '/crm/market/listings',
		label: 'Listings',
		grp: 'Sales and rents',
		status: 'Live',
		tier: 'Tier 1'
	},
	{
		id: 'unit',
		path: '/crm/market/unit',
		label: 'Unit report',
		grp: 'Sales and rents',
		status: 'Live',
		tier: 'Tier 1'
	},
	{
		id: 'launch',
		path: '/crm/market/launch',
		label: 'Launch desk',
		grp: 'Off-plan and land',
		status: 'Live',
		tier: 'Tier 1'
	},
	{
		id: 'plots',
		path: '/crm/market/plots',
		label: 'Plots and feasibility',
		grp: 'Off-plan and land',
		status: 'Live',
		tier: 'Plot valuations · Tier 1 / Feasibility · Tier 3'
	},
	{
		id: 'radar',
		path: '/crm/market/radar',
		label: 'Radar map',
		grp: 'Tools',
		status: 'Being fixed',
		tier: 'Tier 1'
	},
	{
		id: 'chat',
		path: '/crm/market/chat',
		label: 'AI chat',
		grp: 'Tools',
		status: 'Being fixed',
		tier: 'Tier 1'
	}
]

export function screen(id: string): MarketScreen {
	return MARKET_SCREENS.find((s) => s.id === id) ?? MARKET_SCREENS[0]
}

export const TOOL_LINES: Record<string, string> = {
	tx: 'Every registered sale and rental, from DLD and Ejari.',
	an: 'Price, rent and yield by area, project, building and sub-community.',
	ls: "A client's brief, searched in your desk's listings, then the portals.",
	unit: 'One unit on one page, saved as a PDF.',
	launch: 'Off-plan projects and developers.',
	plots: 'Plot valuations and a feasibility model.',
	radar: 'Zones on a map, by layer.',
	chat: 'Questions in plain words, answered with the source and the period.'
}

export const HOME = {
	counters: [
		{
			k: 'Projects',
			v: '1,024',
			n: 'Off-plan, by developer',
			href: '/crm/market/launch',
			src: 'demo' as Src
		},
		{
			k: 'Launch dates',
			v: '13',
			n: 'On the calendar now',
			href: '/crm/market/launch?status=launching',
			src: 'demo' as Src
		},
		{
			k: 'Zones mapped',
			v: '71',
			n: '2,934 projects mapped',
			href: '/crm/market/radar',
			src: 'demo' as Src
		},
		{
			k: 'Al Barsha South 4',
			v: 'AED 1,408 per sqft',
			small: true,
			n: 'Rent AED 55,000 · yield 7.9% · 13,390 transactions, 12 months',
			href: '/crm/market/analytics',
			src: 'demo' as Src
		}
	],
	areas: [
		{
			name: 'Dubai Marina',
			zone: 'dm',
			psf: '1,780',
			rent: '120,000',
			yld: '6.4%',
			note: '1 bed · last 90 days'
		},
		{
			name: 'JVC',
			zone: 'jvc',
			psf: '1,120',
			rent: '78,000',
			yld: '7.6%',
			note: '1 bed · last 90 days'
		}
	]
}

export type TxKind = 'sale' | 'rent'
export type TxUse = 'residential' | 'commercial'
export type Reg = 'deed' | 'oqood' | 'gift' | 'mortgage' | 'ejari'

export interface TxRow {
	n: number
	date: string
	project: string
	building: string | null
	kind: TxKind
	use: TxUse
	type: string
	sqm: number
	price: number
	psm: number
	reg: Reg
}

export const TX = {
	demoCount: { n: 10182, kind: 'sale' as TxKind, use: 'commercial' as TxUse, period: 365 },
	exportLimit: 50000,
	regs: [
		{ id: 'deed', label: 'Title deed' },
		{ id: 'oqood', label: 'Oqood' },
		{ id: 'gift', label: 'Gift' },
		{ id: 'mortgage', label: 'Mortgage' },
		{ id: 'ejari', label: 'Ejari lease' }
	] as { id: Reg; label: string }[],
	periods: [
		{ days: 30, label: 'Last 30 days' },
		{ days: 90, label: 'Last 90 days' },
		{ days: 365, label: 'Last 12 months' }
	],
	cols: [
		{ id: 'date', label: 'Date' },
		{ id: 'project', label: 'Project' },
		{ id: 'building', label: 'Building' },
		{ id: 'unit', label: 'Unit' },
		{ id: 'sqm', label: 'Sqm' },
		{ id: 'price', label: 'Price' },
		{ id: 'psm', label: 'Per sqm' },
		{ id: 'reg', label: 'Registration' }
	],
	rows: [
		{
			n: 1,
			date: '2026-09-28',
			project: 'Skyhills Astra',
			building: null,
			kind: 'sale',
			use: 'commercial',
			type: 'Shop',
			sqm: 374.57,
			price: 10450920,
			psm: 27901,
			reg: 'deed'
		},
		{
			n: 2,
			date: '2026-09-21',
			project: 'Cove Boulevard by Imtiaz',
			building: null,
			kind: 'sale',
			use: 'commercial',
			type: 'Office',
			sqm: 100.99,
			price: 1486163,
			psm: 14716,
			reg: 'oqood'
		},
		{
			n: 3,
			date: '2026-09-15',
			project: 'Shahrukh by Danube',
			building: null,
			kind: 'sale',
			use: 'commercial',
			type: 'Office',
			sqm: 53.42,
			price: 2226240,
			psm: 41674,
			reg: 'oqood'
		},
		{
			n: 4,
			date: '2026-09-09',
			project: 'Shahrukh by Danube',
			building: null,
			kind: 'sale',
			use: 'commercial',
			type: 'Office',
			sqm: 64.65,
			price: 2812600,
			psm: 43505,
			reg: 'oqood'
		},
		{
			n: 5,
			date: '2026-08-30',
			project: 'Cove Boulevard by Imtiaz',
			building: null,
			kind: 'sale',
			use: 'commercial',
			type: 'Office',
			sqm: 77.58,
			price: 1225742,
			psm: 15800,
			reg: 'deed'
		},
		{
			n: 6,
			date: '2026-09-24',
			project: 'Marina Gate',
			building: 'Marina Gate 1',
			kind: 'sale',
			use: 'residential',
			type: '1 bed',
			sqm: 79.9,
			price: 1450000,
			psm: 18148,
			reg: 'deed'
		},
		{
			n: 7,
			date: '2026-07-14',
			project: 'Burj Vista',
			building: 'Burj Vista 1',
			kind: 'sale',
			use: 'residential',
			type: '2 bed',
			sqm: 121.7,
			price: 3640000,
			psm: 29910,
			reg: 'deed'
		},
		{
			n: 8,
			date: '2026-05-20',
			project: 'Burj Vista',
			building: 'Burj Vista 2',
			kind: 'sale',
			use: 'residential',
			type: '2 bed',
			sqm: 119.8,
			price: 3520000,
			psm: 29382,
			reg: 'deed'
		},
		{
			n: 9,
			date: '2026-09-30',
			project: 'Oxford Residence',
			building: 'Oxford Residence',
			kind: 'rent',
			use: 'residential',
			type: '2 bed',
			sqm: 102.2,
			price: 95000,
			psm: 930,
			reg: 'ejari'
		},
		{
			n: 10,
			date: '2025-12-03',
			project: 'Marina Gate',
			building: 'Marina Gate 1',
			kind: 'rent',
			use: 'residential',
			type: '1 bed',
			sqm: 79.9,
			price: 120000,
			psm: 1502,
			reg: 'ejari'
		}
	] as TxRow[]
}

export type LevelId = 'area' | 'proj' | 'bldg' | 'sub'
export const LEVELS: {
	id: LevelId
	level: string
	name: string
	psf: number
	rent: number
	yld: number
	tx: number
	src: Src
}[] = [
	{
		id: 'area',
		level: 'Area',
		name: 'Al Barsha South 4',
		psf: 1408,
		rent: 55000,
		yld: 7.9,
		tx: 13390,
		src: 'demo'
	},
	{
		id: 'proj',
		level: 'Project',
		name: 'Project A, Al Barsha South 4',
		psf: 1465,
		rent: 58000,
		yld: 7.7,
		tx: 2140,
		src: 'ex'
	},
	{
		id: 'bldg',
		level: 'Building',
		name: 'Building A2',
		psf: 1520,
		rent: 61000,
		yld: 7.4,
		tx: 312,
		src: 'ex'
	},
	{
		id: 'sub',
		level: 'Sub-community',
		name: 'Cluster 3',
		psf: 1390,
		rent: 54000,
		yld: 8.0,
		tx: 880,
		src: 'ex'
	}
]

export const QUARTERS = {
	title: 'AED per sqft, last 8 quarters',
	labels: ['Q4 2024', 'Q1 2025', 'Q2 2025', 'Q3 2025', 'Q4 2025', 'Q1 2026', 'Q2 2026', 'Q3 2026'],
	area: [1040, 1080, 1110, 1170, 1220, 1270, 1330, 1390],
	base: 1408
}

export interface MarketListing {
	key: string
	building: string
	unit: string
	desk: boolean
	where: string
	bed: number
	sqft: number
	price: number
}

export const LISTINGS = {
	evidence: { building: 'Burj Vista 1', psf: 2790, period: 'last 12 months' },
	flagAt: 5,
	rows: [
		{
			key: 'd1',
			building: 'Burj Vista 1',
			unit: '1807',
			desk: true,
			where: 'Your desk · listing agent Layla H.',
			bed: 2,
			sqft: 1310,
			price: 3640000
		},
		{
			key: 'p1',
			building: 'Burj Vista 1',
			unit: '3105',
			desk: false,
			where: 'Bayut · agent to agent, Form I first',
			bed: 2,
			sqft: 1335,
			price: 3390000
		},
		{
			key: 'p2',
			building: 'Burj Vista 2',
			unit: '1206',
			desk: false,
			where: 'Property Finder · agent to agent, Form I first',
			bed: 2,
			sqft: 1290,
			price: 3520000
		},
		{
			key: 'p3',
			building: 'Burj Vista 1',
			unit: '0904',
			desk: false,
			where: 'Dubizzle · agent to agent, Form I first',
			bed: 2,
			sqft: 1300,
			price: 3250000
		}
	] as MarketListing[]
}

export interface UnitReport {
	key: string
	name: string
	where: string
	onFile: boolean
	owner: string
	prior: string | null
	bought: string
	lease: string
	worth: string
	yld: string
	bldg: string
	evidence: string
	next: string | null
	pdf: [string, string, string, string]
	bars: number[]
}

export const UNITS = {
	noFile: "Upload your agency's owner file to see if this owner is on your records",
	noPrior: 'Add a prior deal record before contacting',
	rows: [
		{
			key: 'bv',
			name: 'Burj Vista 1 · 2607',
			where: 'Downtown · 2 bed · 1,320 sqft',
			onFile: true,
			owner: 'On your owner file · current owner on DLD',
			prior: 'Prior deal on file · your office let it, Ejari Oct 2025',
			bought: 'AED 2,650,000 · Mar 2017 · mortgage',
			lease: 'AED 275,000 a year · ends 19 Oct 2026',
			worth: 'AED 3.6M to 3.8M · AED 2,730 to 2,880 per sqft',
			yld: "7.4% on today's value",
			bldg: '14 sales · median AED 2,790 per sqft',
			evidence: 'High · 6 sales of the same layout',
			next: 'Renewal call, then a sale conversation',
			pdf: ['AED 2.65M', 'AED 3.6M to 3.8M', 'AED 275,000', '19 Oct 2026'],
			bars: [40, 58, 71, 88]
		},
		{
			key: 'mg',
			name: 'Marina Gate 1 · 1904',
			where: 'Dubai Marina · 1 bed · 860 sqft',
			onFile: true,
			owner: 'On your owner file · current owner on DLD',
			prior: 'Prior deal on file · your office let it, Ejari Dec 2025',
			bought: 'AED 1,420,000 · Jun 2019 · cash',
			lease: 'AED 120,000 a year · ends 2 Dec 2026',
			worth: 'AED 1.48M to 1.58M · AED 1,720 to 1,840 per sqft',
			yld: "7.9% on today's value",
			bldg: '22 sales · median AED 1,780 per sqft',
			evidence: 'High · 9 sales of the same layout',
			next: 'Renewal call: lease ends in 8 weeks',
			pdf: ['AED 1.42M', 'AED 1.48M to 1.58M', 'AED 120,000', '2 Dec 2026'],
			bars: [55, 52, 63, 74]
		},
		{
			key: 'tr',
			name: 'Tiara Residence · 1102',
			where: 'Palm Jumeirah · 2 bed · 1,610 sqft',
			onFile: false,
			owner: 'Not on your owner file',
			prior: null,
			bought: 'AED 3,300,000 · 15% below the sale before it',
			lease: 'AED 310,000 a year · ends 21 Oct 2026',
			worth: 'AED 3.5M to 3.7M',
			yld: '9.39% on the purchase price',
			bldg: '11 sales',
			evidence: 'Medium · 3 sales of the same layout',
			next: null,
			pdf: ['AED 3.3M', 'AED 3.5M to 3.7M', 'AED 310,000', '21 Oct 2026'],
			bars: [82, 70, 66, 78]
		}
	] as UnitReport[]
}

export type LaunchStatus = 'launching' | 'selling'
export const LAUNCH = {
	counters: [
		{ k: 'Projects', v: '1,024', n: 'Filter by developer, delivery date, area, status' },
		{ k: 'Markets', v: '40', n: 'Across the city' },
		{ k: 'Launch dates', v: '13', n: 'On the calendar now' }
	],
	developers: [
		{ name: 'Dubai South', score: '98.7' },
		{ name: 'Emaar', score: '98.3' },
		{ name: 'Nakheel', score: '96.2' },
		{ name: 'Dubai Properties', score: '96.0' },
		{ name: 'Sobha', score: '94.2' },
		{ name: 'Meraas', score: '92.5' },
		{ name: 'DMCC', score: '92.2' },
		{ name: 'Meydan', score: '90.0' },
		{ name: 'Damac', score: '89.1' },
		{ name: 'DIEZ', score: '87.9' }
	],
	projects: [
		{
			key: 'a',
			name: 'Project A',
			handover: 'Q4 2028',
			year: 2028,
			status: 'launching' as LaunchStatus,
			units: 82,
			from: 1150000
		},
		{
			key: 'b',
			name: 'Project B',
			handover: 'Q2 2027',
			year: 2027,
			status: 'selling' as LaunchStatus,
			units: 34,
			from: 1320000
		},
		{
			key: 'c',
			name: 'Project C',
			handover: 'Q1 2029',
			year: 2029,
			status: 'launching' as LaunchStatus,
			units: 120,
			from: 2050000
		}
	],
	fileTabs: [
		{ id: 'br', label: 'Brochure' },
		{ id: 'pp', label: 'Payment plan' },
		{ id: 'cs', label: 'Commission slip' },
		{ id: 'ua', label: 'Units available' },
		{ id: 'rf', label: 'Renders and floorplans' },
		{ id: 'sn', label: 'Site notes' },
		{ id: 'ir', label: 'Project IRR' }
	],
	plan: [
		{ pct: 20, label: 'On booking' },
		{ pct: 50, label: 'During construction' },
		{ pct: 30, label: 'On handover' }
	],
	slip: [
		['Agent commission', '4% of the price'],
		['Paid', 'After 20% is collected'],
		['Slip', 'Ready to download per unit']
	],
	units: {
		a: [
			['1 bed', 42, 1150000],
			['2 bed', 31, 1780000],
			['3 bed', 9, 2640000]
		],
		b: [
			['1 bed', 12, 1320000],
			['2 bed', 22, 1960000]
		],
		c: [
			['2 bed', 64, 2050000],
			['3 bed', 40, 2640000],
			['4 bed', 16, 3900000]
		]
	} as Record<string, [string, number, number][]>,
	renders: ['CGI · front', 'CGI · lobby', '1 bed · 780 sqft', '2 bed · 1,150 sqft'],
	site: [
		['Metro', '6 min'],
		['Mall', '9 min'],
		['School', '12 min'],
		['Airport', '25 min']
	],
	irr: {
		label: 'Estimated, per project',
		value: '12.4%',
		line: "An estimate from the plan and the area's evidence."
	}
}

export const PLOTS = {
	roads: [
		[0, 155, 370, 12],
		[195, 0, 12, 290]
	],
	blocks: [
		[225, 185, 110, 85],
		[350, 40, 20, 110]
	],
	rows: [
		{
			key: 'p1',
			label: 'Plot 1',
			x: 40,
			y: 40,
			w: 150,
			h: 110,
			fields: [
				['Estimate', 'AED 48M · medium confidence'],
				['AED per sqft of GFA', '210'],
				['Plot size', '21,400 sqft'],
				['GFA allowed', '228,000 sqft'],
				['FAR', '10.7'],
				['Use', 'Residential'],
				['Height', 'G + 32'],
				['Nearby plot sales', '4 in 24 months']
			]
		},
		{
			key: 'p2',
			label: 'Plot 2',
			x: 210,
			y: 40,
			w: 120,
			h: 110,
			fields: [
				['Estimate', 'AED 31M · high confidence'],
				['AED per sqft of GFA', '185'],
				['Plot size', '15,800 sqft'],
				['GFA allowed', '167,000 sqft'],
				['FAR', '10.6'],
				['Use', 'Mixed use'],
				['Height', 'G + 25'],
				['Nearby plot sales', '6 in 24 months']
			]
		},
		{
			key: 'p3',
			label: 'Plot 3',
			x: 40,
			y: 170,
			w: 290,
			h: 100,
			fields: [
				['Estimate', 'AED 22M · low confidence'],
				['AED per sqft of GFA', '160'],
				['Plot size', '29,000 sqft'],
				['GFA allowed', '137,000 sqft'],
				['FAR', '4.7'],
				['Use', 'Commercial'],
				['Height', 'G + 8'],
				['Nearby plot sales', '2 in 24 months']
			]
		}
	]
}

export const FEAS = {
	modes: [
		{ id: 'sell', label: 'Build to sell' },
		{ id: 'rent', label: 'Build to rent' },
		{ id: 'lease', label: 'Lease' }
	],
	modelled: 'rent',
	summary: {
		line: 'Build to rent · Business Bay',
		rows: [
			['Rental units modelled', '290'],
			['Leasable area', '22,016 sqm'],
			['Gross potential, a year', 'AED 53,500,000']
		],
		facts: 'Build to rent · Business Bay · 290 units · 22,016 sqm · AED 53,500,000 a year gross',
		irr: ['Project IRR', 'Modelled per plot']
	},
	tabs: [
		{ id: 'sum', label: 'Summary', line: '' },
		{
			id: 'ass',
			label: 'Assumptions',
			line: 'Rents, costs, timing and financing. Each one can be changed.'
		},
		{ id: 'mis', label: 'Missing', line: 'What the model still needs before the numbers hold.' },
		{
			id: 'op',
			label: 'Operating model',
			line: 'Rent roll, vacancy, running costs and net income, year by year.'
		},
		{ id: 'db', label: 'Dev budget', line: 'Land, construction, fees and contingency.' },
		{ id: 'su', label: 'Sources and uses', line: 'Where the money comes from and where it goes.' },
		{ id: 'cap', label: 'Capital stack', line: 'Equity and debt, layer by layer.' },
		{ id: 'cf', label: 'Dev cash flow', line: 'Month by month, from land to completion.' },
		{ id: 'eib', label: 'EIBOR', line: 'The rate the debt is priced on.' },
		{ id: 'chk', label: 'Checks', line: 'Ties every tab out and flags what does not add up.' },
		{
			id: 'rev',
			label: 'Rental evidence',
			line: 'The Ejari contracts behind the rent assumptions.'
		}
	]
}

interface Fig {
	v: string | number
	src: Src
}
export interface Zone {
	key: string
	name: string
	x: number
	y: number
	tx: { v: number; src: Src } | null
	prj: { a: number; d: number; src: Src } | null
	psf: Fig | null
	rent: Fig | null
	yld: Fig | null
	own: { v: number; src: Src } | null
}

export const ZONES = {
	demo: { zones: 71, projects: 2934 },
	sea: 'M0,0 L900,0 L900,30 C760,70 640,95 520,120 C400,145 280,190 170,240 C110,268 50,300 0,320 Z',
	coast: 'M900,30 C760,70 640,95 520,120 C400,145 280,190 170,240 C110,268 50,300 0,320',
	seaLabel: { text: 'Arabian Gulf', x: 250, y: 120 },
	rows: [
		{
			key: 'bb',
			name: 'Business Bay',
			x: 600,
			y: 160,
			tx: { v: 18000, src: 'ex' },
			prj: { a: 53, d: 103, src: 'ex' },
			psf: null,
			rent: null,
			yld: null,
			own: { v: 9, src: 'ex' }
		},
		{
			key: 'abs',
			name: 'Al Barsha South 4',
			x: 395,
			y: 270,
			tx: { v: 13390, src: 'demo' },
			prj: { a: 167, d: 219, src: 'ex' },
			psf: { v: '1,408', src: 'demo' },
			rent: { v: '55,000', src: 'demo' },
			yld: { v: '7.9%', src: 'demo' },
			own: null
		},
		{
			key: 'was',
			name: 'Wadi Al Safa 5',
			x: 600,
			y: 365,
			tx: { v: 7000, src: 'ex' },
			prj: { a: 92, d: 47, src: 'ex' },
			psf: null,
			rent: null,
			yld: null,
			own: null
		},
		{
			key: 'dip',
			name: 'DIP Second',
			x: 210,
			y: 415,
			tx: { v: 6000, src: 'ex' },
			prj: { a: 27, d: 3, src: 'ex' },
			psf: null,
			rent: null,
			yld: null,
			own: null
		},
		{
			key: 'jvc',
			name: 'JVC',
			x: 320,
			y: 310,
			tx: null,
			prj: null,
			psf: null,
			rent: null,
			yld: null,
			own: { v: 14, src: 'ex' }
		},
		{
			key: 'ic',
			name: 'International City',
			x: 790,
			y: 290,
			tx: null,
			prj: null,
			psf: null,
			rent: null,
			yld: null,
			own: { v: 3, src: 'ex' }
		},
		{
			key: 'mk',
			name: 'Al Merkadh',
			x: 660,
			y: 225,
			tx: null,
			prj: null,
			psf: null,
			rent: null,
			yld: null,
			own: null
		},
		{
			key: 'dm',
			name: 'Dubai Marina',
			x: 160,
			y: 250,
			tx: null,
			prj: null,
			psf: null,
			rent: null,
			yld: null,
			own: { v: 22, src: 'ex' }
		},
		{
			key: 'jlt',
			name: 'JLT',
			x: 225,
			y: 280,
			tx: null,
			prj: null,
			psf: null,
			rent: null,
			yld: null,
			own: { v: 6, src: 'ex' }
		},
		{
			key: 'dsc',
			name: 'Dubai Sports City',
			x: 285,
			y: 370,
			tx: null,
			prj: null,
			psf: null,
			rent: null,
			yld: null,
			own: { v: 4, src: 'ex' }
		}
	] as Zone[]
}

export type LayerId = 'act' | 'prj' | 'own'
export const LAYERS: { id: LayerId; label: string; measure: string; status: Status }[] = [
	{ id: 'act', label: 'Transactions', measure: 'transactions', status: 'Being fixed' },
	{ id: 'prj', label: 'Projects', measure: 'active and done projects', status: 'Being fixed' },
	{
		id: 'own',
		label: 'Your owners with an event',
		measure: "owners on your agency's own file with an event",
		status: 'Not yet'
	}
]
export const OTHER_LAYERS =
	'Other layers in the platform, not in this mockup: price per sqft, yield, status, risk, developer, planning.'

export interface Answer {
	key: string | null
	text: string
	rows?: [string, string][] | null
	table?: { head: string[]; body: string[][] } | null
	chart?: { title: string; horizontal?: boolean; points: [string, number][] } | null
	ref?: { href: string; label: string } | null
	source: string
	label: string
	note?: string | null
}

export const QUESTIONS: (Answer & { q: string })[] = [
	{
		key: 'q1',
		q: 'What do 2 beds in JVC rent for now?',
		text: 'A 2 bed in JVC rents for a median of AED 95,000 a year, from 214 Ejari contracts in the last 90 days.',
		rows: [
			['Median', 'AED 95,000'],
			['Range', 'AED 82,000 to 112,000'],
			['Contracts', '214']
		],
		chart: {
			title: 'Median by quarter, last 4 quarters',
			points: [
				['Q4 2025', 84000],
				['Q1 2026', 88000],
				['Q2 2026', 91000],
				['Q3 2026', 95000]
			]
		},
		ref: { href: '/crm/market/radar?zone=jvc', label: 'Open Radar map' },
		source: 'Ejari contracts · 2 bed · JVC · last 90 days',
		label: LABELS.ex
	},
	{
		key: 'q2',
		q: 'Compare yields: JVC against Dubai Marina',
		text: 'Gross yield over the last 12 months: JVC 7.6%, Dubai Marina 6.4%.',
		rows: [
			['JVC', '7.6%'],
			['Dubai Marina', '6.4%']
		],
		chart: {
			title: 'Gross yield, last 12 months',
			horizontal: true,
			points: [
				['JVC', 7.6],
				['Dubai Marina', 6.4]
			]
		},
		ref: { href: '/crm/market/radar?zone=jvc', label: 'Open Radar map' },
		source: 'Gross yield · DLD sales and Ejari rents · last 12 months',
		label: LABELS.ex
	},
	{
		key: 'q3',
		q: 'Comparable sales for Burj Vista 1, 2 bed',
		text: 'Three sales of the same layout in the last 6 months.',
		table: {
			head: ['Building', 'Sqft', 'AED', 'Date'],
			body: [
				['Burj Vista 1', '1,310', '3,640,000', 'Jul 2026'],
				['Burj Vista 1', '1,335', '3,810,000', 'Jun 2026'],
				['Burj Vista 2', '1,290', '3,520,000', 'May 2026']
			]
		},
		ref: { href: '/crm/market/unit?unit=bv', label: 'Open Unit report' },
		source: 'DLD sales · same building and layout · last 6 months',
		label: LABELS.ex
	},
	{
		key: 'q4',
		q: 'Write a listing description for Marina Gate 1, 1 bed',
		text: '1 bed in Marina Gate 1, 860 sqft, high floor, marina view. Vacant from 2 December. Covered parking, pool and gym in the building. A 5-minute walk to Dubai Marina Mall and the tram.',
		ref: { href: '/crm/market/unit?unit=mg', label: 'Open Unit report' },
		source: 'Unit record and building details',
		label: LABELS.ex,
		note: 'Needs a Trakheesi permit number before it goes on a portal.'
	}
]

export const NO_ANSWER = 'No answer for that in this mockup. Try one of the suggested questions.'
export const CHAT_FOOTER = 'On the phone, the Telegram assistant asks this same chat.'

function words(q: string): string {
	return ` ${q
		.toLowerCase()
		.replace(/[^a-z0-9\s]/g, ' ')
		.replace(/\s+/g, ' ')
		.trim()} `
}

/** Example answers from the data above (spec section 6). Unknown questions get NO_ANSWER. */
export function answer(question: string): Answer {
	const s = words(question)
	const has = (w: string) => s.includes(` ${w}`)
	const pick = (k: string) => QUESTIONS.find((x) => x.key === k) as Answer
	if (has('jvc') && (has('rent') || has('rents'))) return pick('q1')
	if (has('yield') && has('jvc') && has('marina')) return pick('q2')
	if (has('burj vista') && (has('comparable') || has('sales') || has('comps'))) return pick('q3')
	if (has('listing description') || (has('describe') && has('marina gate'))) return pick('q4')
	if (has('al barsha south 4')) {
		const a = LEVELS[0]
		return {
			key: 'area',
			text: `${a.name}: AED ${a.psf.toLocaleString('en-US')} per sqft, rent AED ${a.rent.toLocaleString('en-US')} a year, ${a.yld.toFixed(1)}% gross yield, ${a.tx.toLocaleString('en-US')} transactions in 12 months.`,
			ref: { href: '/crm/market/analytics', label: 'Open Analytics' },
			source: 'DLD sales and Ejari leases · last 12 months',
			label: LABELS.demo
		}
	}
	if (has('launch') || has('off plan') || has('projects')) {
		return {
			key: 'launch',
			text: '1,024 off-plan projects across 40 markets, with 13 launch dates on the calendar.',
			rows: [
				['Projects', '1,024'],
				['Markets', '40'],
				['Launch dates', '13']
			],
			ref: { href: '/crm/market/launch', label: 'Open Launch desk' },
			source: 'Launch desk',
			label: LABELS.demo
		}
	}
	return { key: null, text: NO_ANSWER, source: '', label: LABELS.ex }
}

export function num(n: number): string {
	return Math.round(n).toLocaleString('en-US')
}

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function fDay(iso: string): string {
	const [y, m, d] = iso.split('-').map(Number)
	return `${d} ${MON[m - 1]} ${y}`
}
export function addDays(iso: string, n: number): string {
	const d = new Date(`${iso}T00:00:00Z`)
	d.setUTCDate(d.getUTCDate() + n)
	return d.toISOString().slice(0, 10)
}
