import { client } from './client'
import type {
	ComparableData,
	GisPlotDossier,
	GisPlotSummary,
	HbuStudy
} from './generated/hey-api/types.gen'

export type { ComparableData, GisPlotDossier, GisPlotSummary, HbuStudy }

export const feasibility = {
	getAreas(): Promise<string[]> {
		return client.get('/api/v1/feasibility/areas')
	},

	getCommunities(): Promise<string[]> {
		return client.get('/api/v1/feasibility/communities')
	},

	searchPlots(params: {
		q?: string
		community?: string
		minPlotAreaSqm?: number
		maxPlotAreaSqm?: number
		offset?: number
		limit?: number
	}): Promise<GisPlotSummary[]> {
		return client.get(
			client.withQuery('/api/v1/feasibility/plots', {
				q: params.q,
				community: params.community,
				min_plot_area_sqm: params.minPlotAreaSqm,
				max_plot_area_sqm: params.maxPlotAreaSqm,
				offset: params.offset,
				limit: params.limit
			})
		)
	},

	getPlotDossier(plotNumber: string): Promise<GisPlotDossier> {
		return client.get(`/api/v1/feasibility/plots/${encodeURIComponent(plotNumber)}`)
	},

	generateHBUStudy(
		plotNumber: string,
		usageOverride?: GisPlotDossier['inferred_usage']
	): Promise<HbuStudy> {
		return client.post(
			client.withQuery(`/api/v1/feasibility/hbu/${encodeURIComponent(plotNumber)}`, {
				usage_override: usageOverride && usageOverride !== 'unknown' ? usageOverride : undefined
			})
		)
	},

	searchLandPlots(area: string, q: string): Promise<GisPlotSummary[]> {
		return client.get(client.withQuery('/api/v1/feasibility/land/search', { area, q }))
	},

	getLandPlots(area: string, sizeSqm: number, tolerance = 0.25): Promise<GisPlotSummary[]> {
		return client.get(
			client.withQuery('/api/v1/feasibility/land', {
				area,
				size_sqm: sizeSqm,
				tolerance
			})
		)
	},

	getComparableData(projectIds: number[]): Promise<ComparableData> {
		return client.get(
			client.withQuery('/api/v1/feasibility/comparable', {
				project_ids: projectIds.join(',')
			})
		)
	},

	streamChat(
		messages: Array<{ role: string; content: string }>,
		context: object,
		historyJson: string | null,
		onChunk: (data: string) => void
	) {
		return client.stream('/api/v1/feasibility/chat/stream', onChunk, {
			method: 'POST',
			body: { messages, context, history_json: historyJson }
		})
	}
}
