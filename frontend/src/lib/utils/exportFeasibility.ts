import * as XLSX from 'xlsx';
import type { feasibilityStore as FeasibilityStore } from '$lib/stores/feasibility.svelte';

type Store = typeof FeasibilityStore;

function r(n: number) { return Math.round(n); }
function pct(n: number) { return `${n.toFixed(1)}%`; }
function irrFmt(v: number) { return isNaN(v) ? '—' : pct(v * 100); }

export function exportFeasibility(s: Store) {
	const a = s.assumptions;
	const wb = XLSX.utils.book_new();

	// ── Revenue ────────────────────────────────────────────────────────────────
	const revenueRows: unknown[][] = [
		['Type', 'Count', 'Avg sqm', 'Total sqm', 'AED/sqm', 'GDV (AED)', '% of GDV'],
		...s.spreadsheetRows.map((row) => {
			const totalArea = row.count * row.avgSizeSqm;
			const gdvPct = s.totalGDV > 0 ? (row.totalProceeds / s.totalGDV) * 100 : 0;
			return [row.type, row.count, +row.avgSizeSqm.toFixed(1), r(totalArea), row.pricePerSqm, r(row.totalProceeds), +gdvPct.toFixed(1)];
		}),
		['Total', s.totalUnits, '', r(s.totalSellableAreaSqm), '', r(s.totalGDV), 100],
		[],
		['', 'Pre-handover', 'Post-handover', 'Total'],
		['Units', s.preHandoverUnits, s.postHandoverUnits, s.totalUnits],
		['GDV (AED)', r(s.preHandoverGDV), r(s.postHandoverGDV), r(s.totalBlendedGDV)],
		[],
		['Total GDV (market prices)', r(s.totalGDV)],
		['Blended GDV (with discount)', r(s.totalBlendedGDV)],
		[`Less: Agent Commission (${a.agentCommissionPct}%)`, -r(s.agentFees)],
		[`Less: Marketing (${a.marketingBudgetPct}%)`, -r(s.marketingCost)],
		['Net Revenue', r(s.netRevenue)],
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(revenueRows), 'Revenue');

	// ── Dev Budget ─────────────────────────────────────────────────────────────
	const devBudgetRows: unknown[][] = [
		['Item', 'AED'],
		['LAND ACQUISITION'],
		['Land Purchase Price', a.landCost],
		[`DLD Transfer Fee (${a.transferFeePct}%)`, r(s.transferFees)],
		['Total Land Cost', r(s.totalLandCost)],
		[],
		['HARD CONSTRUCTION COSTS'],
		[`Build Cost/sqm × ${r(s.totalSellableAreaSqm)} sqm`, r(s.hardCost)],
		[`Contingency (${a.contingencyPct}%)`, r(s.contingencyCost)],
		['Total Hard Costs', r(s.totalHardCost)],
		[],
		[`SOFT COSTS (${a.softCostsPct}% of hard)`],
		[`Design & Engineering (${a.designFeePct}%)`, r(s.designCost)],
		[`Project Management (${a.projectMgmtPct}%)`, r(s.projectMgmtCost)],
		['Other Soft Costs', r(s.otherSoftCost)],
		['Total Soft Costs', r(s.totalSoftCost)],
		[],
		['SALES & MARKETING'],
		[`Agent Commission (${a.agentCommissionPct}% of GDV)`, r(s.agentFees)],
		[`Marketing Budget (${a.marketingBudgetPct}% of GDV)`, r(s.marketingCost)],
		['Total Sales Costs', r(s.totalSalesCost)],
		[],
		['FINANCE'],
		[`Loan Amount (${(a.debtToCostRatio * 100).toFixed(0)}% of pre-finance cost)`, r(s.debtAmount)],
		[`Interest (${a.financeRatePct}% p.a., ${s.interestOnlyMonths} months)`, r(s.totalInterest)],
		[`Arrangement Fee (${a.arrangementFeePct}%)`, r(s.arrangementFee)],
		['Total Finance Costs', r(s.totalFinanceCost)],
		[],
		['TOTAL DEVELOPMENT COST', r(s.totalDevCost)],
		['Gross Profit', r(s.grossProfit)],
		['Return on Cost', pct(s.returnOnCost)],
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(devBudgetRows), 'Dev Budget');

	// ── Schedule ───────────────────────────────────────────────────────────────
	const scheduleRows: unknown[][] = [
		['Parameter', 'Value'],
		['Construction Period (months)', a.constructionMonths],
		['Sales Launch (month from start)', a.salesLaunchMonth],
		['Sales Duration (months)', a.salesMonths],
		['Total Quarters', s.totalQ],
		[],
		['Quarter', 'Land', 'Construction', 'Soft Costs', 'Marketing', 'Total Costs', 'Revenue', 'Net', 'Cumulative'],
		...s.cashflow.map((p) => [
			`Q${p.q + 1}`,
			p.land ? r(p.land) : '',
			p.construction ? r(p.construction) : '',
			p.soft ? r(p.soft) : '',
			p.marketing ? r(p.marketing) : '',
			r(p.costs),
			p.revenue ? r(p.revenue) : '',
			r(p.net),
			r(p.cum),
		]),
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(scheduleRows), 'Schedule');

	// ── Cash Flow ──────────────────────────────────────────────────────────────
	const cashFlowRows: unknown[][] = [
		['Quarter', 'Land', 'Construction', 'Soft Costs', 'Selling & Mkt', 'Total Outflows', 'Sales Revenue', 'Net Cash Flow', 'Cumulative'],
		...s.cashflow.map((p) => [
			`Q${p.q + 1}`,
			p.land ? r(p.land) : '',
			p.construction ? r(p.construction) : '',
			p.soft ? r(p.soft) : '',
			p.marketing ? r(p.marketing) : '',
			r(p.costs),
			p.revenue ? r(p.revenue) : '',
			r(p.net),
			r(p.cum),
		]),
		[],
		['Peak Funding Required (AED)', r(s.peakFunding)],
		['Cash Breakeven Quarter', s.cashBreakevenQuarter >= 0 ? `Q${s.cashBreakevenQuarter + 1}` : '—'],
		['Total Interest (AED)', r(s.totalInterest)],
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(cashFlowRows), 'Cash Flow');

	// ── Returns ────────────────────────────────────────────────────────────────
	const returnsRows: unknown[][] = [
		['Metric', 'Unlevered', 'Levered'],
		['Investment (AED)', r(s.totalDevCost), r(s.equityRequired)],
		['Net Revenue (AED)', r(s.netRevenue), r(s.netRevenue)],
		['Gross Profit (AED)', r(s.grossProfit), r(s.grossProfit)],
		['Profit Margin', pct((s.grossProfit / Math.max(1, s.totalBlendedGDV)) * 100), ''],
		['Return on Cost', pct(s.returnOnCost), '—'],
		['Return on Equity', '—', pct(s.returnOnEquity)],
		['Equity Multiple', '—', `${s.equityMultiple.toFixed(2)}×`],
		['IRR (annualised)', irrFmt(s.unleveredIRR), irrFmt(s.leveredIRR)],
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(returnsRows), 'Returns');

	// ── Assumptions ────────────────────────────────────────────────────────────
	const assumptionsRows: unknown[][] = [
		['Parameter', 'Value'],
		['LAND & SITE'],
		['Land Cost (AED)', a.landCost],
		['DLD Transfer Fee (%)', a.transferFeePct],
		[],
		['CONSTRUCTION'],
		['Build Cost/sqm (AED)', a.buildCostPerSqm],
		['Contingency (%)', a.contingencyPct],
		['Construction Period (months)', a.constructionMonths],
		['Soft Costs total (% of hard)', a.softCostsPct],
		['  Design & Engineering (%)', a.designFeePct],
		['  Project Management (%)', a.projectMgmtPct],
		[],
		['SALES & MARKETING'],
		['Sales Launch (months from start)', a.salesLaunchMonth],
		['Sales Duration (months)', a.salesMonths],
		['Agent Commission (% of GDV)', a.agentCommissionPct],
		['Marketing Budget (% of GDV)', a.marketingBudgetPct],
		['Presale Discount (%)', a.presaleDiscountPct],
		['Price Escalation p.a. (%)', a.priceEscalationPct],
		['Post-handover Unsold (%)', a.postHandoverSalesPct],
		[],
		['FINANCING'],
		['Debt-to-Cost Ratio (%)', +(a.debtToCostRatio * 100).toFixed(0)],
		['Interest Rate (% p.a.)', a.financeRatePct],
		['Arrangement Fee (%)', a.arrangementFeePct],
		['Interest-only Period (months)', s.interestOnlyMonths],
		[],
		['MACRO'],
		['Inflation / Cost Escalation (%)', a.inflationPct],
		['Discount Rate (%)', a.discountRatePct],
		['Rental Yield Assumption (%)', a.rentalYieldPct],
		['Target ROC (%)', a.targetROCPct],
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(assumptionsRows), 'Assumptions');

	// ── Download ───────────────────────────────────────────────────────────────
	const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
	const blob = new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
	const url = URL.createObjectURL(blob);
	const anchor = document.createElement('a');
	anchor.href = url;
	anchor.download = `feasibility_${Date.now()}.xlsx`;
	anchor.click();
	URL.revokeObjectURL(url);
}
