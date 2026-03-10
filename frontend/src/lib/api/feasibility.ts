import type {
	ComparableData,
	GISPlotDossier,
	GISPlotSummary,
	HBUStudy
} from '$lib/stores/feasibility.svelte'
import { api, stream } from './client'

export type { ComparableData, GISPlotDossier, GISPlotSummary, HBUStudy }

export const feasibility = {
	getAreas(): Promise<string[]> {
		return api('/api/v1/feasibility/areas')
	},

	getCommunities(): Promise<string[]> {
		return api('/api/v1/feasibility/communities')
	},

	searchPlots(params: {
		q?: string
		community?: string
		minPlotAreaSqm?: number
		maxPlotAreaSqm?: number
		offset?: number
		limit?: number
	}): Promise<GISPlotSummary[]> {
		const query = new URLSearchParams()
		if (params.q) query.set('q', params.q)
		if (params.community) query.set('community', params.community)
		if (params.minPlotAreaSqm !== undefined)
			query.set('min_plot_area_sqm', params.minPlotAreaSqm.toString())
		if (params.maxPlotAreaSqm !== undefined)
			query.set('max_plot_area_sqm', params.maxPlotAreaSqm.toString())
		if (params.offset !== undefined) query.set('offset', params.offset.toString())
		if (params.limit !== undefined) query.set('limit', params.limit.toString())
		return api(`/api/v1/feasibility/plots?${query}`)
	},

	getPlotDossier(plotNumber: string): Promise<GISPlotDossier> {
		return api(`/api/v1/feasibility/plots/${encodeURIComponent(plotNumber)}`)
	},

	generateHBUStudy(
		plotNumber: string,
		usageOverride?: GISPlotDossier['inferred_usage']
	): Promise<HBUStudy> {
		const params = new URLSearchParams()
		if (usageOverride && usageOverride !== 'unknown') params.set('usage_override', usageOverride)
		const suffix = params.toString() ? `?${params}` : ''
		return api(`/api/v1/feasibility/hbu/${encodeURIComponent(plotNumber)}${suffix}`, {
			method: 'POST'
		})
	},

	searchLandPlots(area: string, q: string): Promise<GISPlotSummary[]> {
		const params = new URLSearchParams({ area, q })
		return api(`/api/v1/feasibility/land/search?${params}`)
	},

	getLandPlots(area: string, sizeSqm: number, tolerance = 0.25): Promise<GISPlotSummary[]> {
		const params = new URLSearchParams({
			area,
			size_sqm: sizeSqm.toString(),
			tolerance: tolerance.toString()
		})
		return api(`/api/v1/feasibility/land?${params}`)
	},

	getComparableData(projectIds: number[]): Promise<ComparableData> {
		return api(`/api/v1/feasibility/comparable?project_ids=${projectIds.join(',')}`)
	},

	streamChat(
		messages: Array<{ role: string; content: string }>,
		context: object,
		historyJson: string | null,
		onChunk: (data: string) => void
	) {
		return stream('/api/v1/feasibility/chat/stream', onChunk, {
			method: 'POST',
			body: { messages, context, history_json: historyJson }
		})
	}
}
