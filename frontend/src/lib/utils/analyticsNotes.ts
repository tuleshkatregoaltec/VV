import type {
	AnalyticsSummary,
	ProjectForecastResponse,
	ProjectPipelineResponse,
	RentalSummary
} from '$lib/api/analytics'

// Customer-facing notes for Analytics widgets: they say what a figure covers or why it is
// missing, and never name the data providers.

/** Why the price forecast is missing, or null when there is one (or nothing loaded yet). */
export function forecastNote(
	forecast: Pick<ProjectForecastResponse, 'available' | 'data' | 'methodology'> | null | undefined
): string | null {
	if (!forecast || forecast.available) return null
	return 'A price forecast is not available: the records hold no delivery schedule to anchor one on. The supply pipeline below shows expected completions.'
}

/** Which projects the supply pipeline counts: its area's, not only the selection's own. */
export function pipelineBasisNote(
	pipeline: Pick<ProjectPipelineResponse, 'area_name' | 'data'> | null | undefined
): string | null {
	const area = pipeline?.area_name
	if (!area) return null
	if (area === 'Dubai') return 'Counts every registered project in Dubai.'
	return `Counts every registered project in ${area}, the area of this selection, not only its own projects.`
}

/** Gross yield (%) from the median annual rent and the median sale price. */
export function grossYieldPct(
	rent: Pick<RentalSummary, 'median_annual_rent'> | null | undefined,
	sales: Pick<AnalyticsSummary, 'median_price'> | null | undefined
): number | null {
	const medianRent = rent?.median_annual_rent ?? 0
	const medianPrice = sales?.median_price ?? 0
	if (medianRent <= 0 || medianPrice <= 0) return null
	return (medianRent / medianPrice) * 100
}

/** A note for trend points the selected range cuts (a part of a week or month). */
export function partialPeriodsNote(
	points: { date: string; partial?: boolean }[] | null | undefined
): string | null {
	if (!points?.length) return null
	const first = points.length > 1 && Boolean(points[0].partial)
	const last = Boolean(points[points.length - 1].partial)
	if (first && last) return 'The first and last periods are partial: the selected range cuts them.'
	if (first) return 'The first period is partial: the selected range cuts it.'
	if (last) return 'The last period is partial: the selected range cuts it.'
	return null
}
