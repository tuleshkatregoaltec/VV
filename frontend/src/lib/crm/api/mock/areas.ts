/**
 * Area reference figures used only by the fixture backend (feed rows, owner reports). In
 * production these come from the Transactions and Analytics data.
 */
export interface AreaStats {
	psf: number
	rent: number
	yld: number
}

export const AREA_STATS: Record<string, AreaStats> = {
	Bluewaters: { psf: 3300, rent: 210000, yld: 5.1 },
	'Palm Jumeirah': { psf: 4200, rent: 320000, yld: 4.8 },
	'City Walk': { psf: 2700, rent: 150000, yld: 5.6 },
	DIFC: { psf: 2600, rent: 140000, yld: 5.8 },
	'Dubai Marina': { psf: 2150, rent: 120000, yld: 6.4 },
	JLT: { psf: 1450, rent: 85000, yld: 7.3 },
	'Al Quoz': { psf: 1250, rent: 70000, yld: 7.0 },
	Downtown: { psf: 3000, rent: 160000, yld: 5.4 },
	'Business Bay': { psf: 2100, rent: 105000, yld: 6.6 },
	'Creek Harbour': { psf: 2250, rent: 110000, yld: 6.1 },
	Mirdif: { psf: 1100, rent: 110000, yld: 6.0 },
	'Al Barsha South': { psf: 1408, rent: 55000, yld: 7.9 },
	'Dubai Hills': { psf: 2300, rent: 150000, yld: 5.9 },
	Meydan: { psf: 1800, rent: 95000, yld: 6.8 },
	'Al Furjan': { psf: 1300, rent: 80000, yld: 7.2 },
	JVT: { psf: 1250, rent: 75000, yld: 7.5 },
	JVC: { psf: 1200, rent: 70000, yld: 7.8 },
	'Motor City': { psf: 1150, rent: 80000, yld: 7.1 },
	'International City': { psf: 750, rent: 42000, yld: 9.1 },
	'Dubai Sports City': { psf: 1000, rent: 60000, yld: 8.2 },
	'Arabian Ranches': { psf: 1600, rent: 220000, yld: 5.2 },
	'Dubai South': { psf: 1000, rent: 55000, yld: 7.4 },
	'Damac Hills': { psf: 1350, rent: 140000, yld: 6.3 },
	'Town Square': { psf: 1050, rent: 65000, yld: 7.6 }
}

const BUILDINGS: Record<string, string[]> = {
	'Dubai Marina': ['Marina Gate 2', 'Marina Heights', 'Marina Promenade'],
	JVC: ['Bellavista', 'Zada Tower', 'Bloom Towers'],
	'Business Bay': ['Executive Bay', 'Bay Square', 'Executive Tower'],
	Downtown: ['Burj Vista 1', 'Downtown Views II', 'Boulevard Heights'],
	'Palm Jumeirah': ['Palm Tiara', 'Tiara Residences', 'Frond Villas'],
	'Dubai Hills': ['Golf Place', 'Golf Suites', 'Park Heights'],
	JLT: ['Cluster D', 'Cluster Y', 'Lake Terrace'],
	'Creek Harbour': ['Creek Rise', 'Harbour Views', 'Creek Edge']
}

export function buildingsOf(area: string): string[] {
	return BUILDINGS[area] ?? [`${area} Residences`, `${area} Heights`, `${area} Gardens`]
}

/** Which area a free-text unit ("Bellavista · 1BR") sits in. */
export function areaOfUnit(unit: string): string {
	const direct = Object.keys(AREA_STATS).find((a) => unit.includes(a))
	if (direct) return direct
	const byBuilding = Object.keys(BUILDINGS).find((a) => BUILDINGS[a].some((b) => unit.includes(b)))
	return byBuilding ?? 'JVC'
}

/** Rent multiplier and typical size by bedrooms (studio … 4BR). */
export const BED_FACTOR = [0.55, 0.8, 1.2, 1.75, 2.8]
export const BED_SQFT = [420, 760, 1200, 1750, 3400]

export const FEED_OWNERS = [
	'M. Al Hashimi',
	'R. Kapoor',
	'S. Petrov',
	'A. Haddad',
	'L. Chen',
	'F. Rahman',
	'J. Walker',
	'N. Saeed',
	'H. Nasser',
	'P. Menon',
	'K. Ibrahim',
	'D. Novak'
]

/** Small deterministic PRNG so the same page of the feed always shows the same owners. */
export function rng(seed: number): () => number {
	let s = seed | 0
	return () => {
		s = (s + 0x6d2b79f5) | 0
		let t = Math.imul(s ^ (s >>> 15), 1 | s)
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296
	}
}
