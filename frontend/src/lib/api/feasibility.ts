import type { FeasibilityStudy } from '$lib/feasibility/workbook/models'
import { client } from './client'
import type {
	FeasibilityAssumptions,
	Plot,
	PlotDetails,
	PlotResearch
} from './generated/hey-api/types.gen'

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
	}): Promise<Plot[]> {
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

	async searchAllCommunityPlots(community: string, pageSize = 100): Promise<Plot[]> {
		const allPlots: Plot[] = []
		let offset = 0
		while (true) {
			const page = await this.searchPlots({
				community,
				offset,
				limit: pageSize
			})
			allPlots.push(...page)
			if (page.length < pageSize) break
			offset += page.length
		}
		return allPlots
	},

	getPlotData(plotNumber: string): Promise<PlotDetails> {
		return client.get(`/api/v1/feasibility/plots/${encodeURIComponent(plotNumber)}`)
	},

	generateStudy(params: {
		plot_number: string
		usage_override?: 'residential' | 'commercial' | 'mixed_use' | 'unknown'
	}): Promise<FeasibilityStudy> {
		return client.post('/api/v1/feasibility/generate-study', params)
	},

	streamChat(
		messages: Array<{ role: string; content: string }>,
		params: {
			plot_data: FeasibilityStudy['plot_data']
			assumptions: FeasibilityAssumptions
			research: PlotResearch
		},
		onChunk: (data: string) => void
	) {
		return client.stream('/api/v1/feasibility/chat/stream', onChunk, {
			method: 'POST',
			body: {
				messages,
				plot_data: params.plot_data,
				assumptions: params.assumptions,
				research: params.research
			}
		})
	}
}
