export type ResearchTab = 'summary' | 'transactions' | 'analytics' | 'map';

export interface AgentTransactionData {
	rows: Record<string, unknown>[];
	filters: { area: string; unit_type: string; days: number };
	count: number;
}

export interface AgentAnalyticsData {
	trend: Array<{ month: string; median_price_sqm: number; txn_count: number }>;
	by_rooms: Array<{ rooms_en: string; txn_count: number; median_price_sqm: number; avg_area_sqm: number }>;
	filters: { area: string; project_name: string; days: number };
}

const activeTab = $state({ value: 'summary' as ResearchTab });
const agentTransactions = $state({ value: null as AgentTransactionData | null });
const agentAnalytics = $state({ value: null as AgentAnalyticsData | null });
const txFilters = $state({ value: { unitType: '', days: 365 } });
const comparableMarketPrices = $state({ value: null as Record<string, number> | null });

export const researchPanelStore = {
	get activeTab() { return activeTab.value; },
	get agentTransactions() { return agentTransactions.value; },
	get agentAnalytics() { return agentAnalytics.value; },
	get txFilters() { return txFilters.value; },
	get comparableMarketPrices() { return comparableMarketPrices.value; },

	setActiveTab(tab: ResearchTab) { activeTab.value = tab; },
	setAgentData(tab: 'transactions' | 'analytics', data: unknown) {
		if (tab === 'transactions') agentTransactions.value = data as AgentTransactionData;
		if (tab === 'analytics') agentAnalytics.value = data as AgentAnalyticsData;
	},
	setTxFilter(patch: Partial<{ unitType: string; days: number }>) {
		txFilters.value = { ...txFilters.value, ...patch };
	},
	setComparableMarketPrices(prices: Record<string, number>) {
		comparableMarketPrices.value = prices;
	},
};
