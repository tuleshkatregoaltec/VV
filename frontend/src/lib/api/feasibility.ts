import { api, stream } from './client';
import type { LandPlot, ComparableData } from '$lib/stores/feasibility.svelte';

export type { LandPlot, ComparableData };

export const feasibility = {
	getAreas(): Promise<string[]> {
		return api('/api/v1/feasibility/areas');
	},

	getLandPlots(area: string, sizeSqm: number, tolerance = 0.25): Promise<LandPlot[]> {
		const params = new URLSearchParams({
			area,
			size_sqm: sizeSqm.toString(),
			tolerance: tolerance.toString(),
		});
		return api(`/api/v1/feasibility/land?${params}`);
	},

	getComparableData(projectIds: number[]): Promise<ComparableData> {
		return api(`/api/v1/feasibility/comparable?project_ids=${projectIds.join(',')}`);
	},

	streamChat(
		messages: Array<{ role: string; content: string }>,
		context: object,
		onChunk: (data: string) => void
	) {
		return stream('/api/v1/feasibility/chat/stream', onChunk, {
			method: 'POST',
			body: { messages, context },
		});
	},
};
