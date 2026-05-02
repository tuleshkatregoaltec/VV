import type {
	FeasibilityStudy,
	PlotDataResponse,
	FeasibilityAssumptions as WorkbookFeasibilityAssumptions
} from '$lib/feasibility/workbook/models'
import { client } from './client'
import type { Plot, PlotDetails, PlotResearch } from './generated/hey-api/types.gen'

export function normalizePlotDataResponse(
	response: PlotDataResponse | PlotDetails
): PlotDataResponse {
	return 'plot_data' in response ? response : { plot_data: response }
}

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

	async getPlotData(plotNumber: string): Promise<PlotDataResponse> {
		const response = await client.get<PlotDataResponse | PlotDetails>(
			`/api/v1/feasibility/plots/${encodeURIComponent(plotNumber)}`
		)
		return normalizePlotDataResponse(response)
	},

	generateStudy(params: {
		plot_number: string
		usage_override?: 'residential' | 'commercial' | 'mixed_use' | 'unknown'
		development_model?:
			| 'build_to_sell_residential'
			| 'build_to_rent_residential'
			| 'build_to_lease_commercial'
	}): Promise<FeasibilityStudy> {
		return client.post('/api/v1/feasibility/generate-study', params)
	},

	streamChat(
		messages: Array<{ role: string; content: string }>,
		params: {
			plot_data: FeasibilityStudy['plot_data']
			assumptions: WorkbookFeasibilityAssumptions
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
