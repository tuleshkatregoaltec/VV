import * as XLSX from 'xlsx';
import type { feasibilityStore as FeasibilityStore } from '$lib/stores/feasibility.svelte';

type Store = typeof FeasibilityStore;

function r(n: number) {
	return Math.round(n);
}
function pct(n: number) {
	return `${n.toFixed(1)}%`;
}
function irrFmt(v: number) {
	return isNaN(v) || !isFinite(v) ? '—' : pct(v * 100);
}
function fmtK(n: number) {
	return isFinite(n) ? r(n / 1000) : '—';
}

export function exportFeasibility(s: Store) {
	const a = s.assumptions;
	const wb = XLSX.utils.book_new();

	// ── Revenue ────────────────────────────────────────────────────────────────
	const revenueRows: unknown[][] = [
		['Type', 'Count', 'Avg sqm', 'Total sqm', 'AED/sqm', 'GDV (AED)', '% of GDV'],
		...s.spreadsheetRows.map((row) => {
			const totalArea = row.count * row.avgSizeSqm;
			const gdvPct = s.totalGDV > 0 ? (row.totalProceeds / s.totalGDV) * 100 : 0;
			return [
				row.type,
				row.count,
				+row.avgSizeSqm.toFixed(1),
				r(totalArea),
				row.pricePerSqm,
				r(row.totalProceeds),
				+gdvPct.toFixed(1)
			];
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
		...(s.retailAnnualIncome > 0
			? [
					[],
					['ANCILLARY RETAIL INCOME'],
					['Annual Rental Income (AED)', r(s.retailAnnualIncome)],
					['Capitalised Value (AED)', r(s.retailCapValue)]
				]
			: [])
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
		['INFRASTRUCTURE & AUTHORITY FEES'],
		...(a.infrastructureCostAED > 0
			? [['Infrastructure Works (AED)', a.infrastructureCostAED]]
			: []),
		...(a.authorityConnectionFeesAED > 0
			? [['Authority Connection Fees (AED)', a.authorityConnectionFeesAED]]
			: []),
		...(a.communityMasterDevFeesAED > 0
			? [['Community / Master-dev Fees (AED)', a.communityMasterDevFeesAED]]
			: []),
		...(a.hasDemolition && a.demolitionCostAED > 0
			? [['Demolition Cost (AED)', a.demolitionCostAED]]
			: []),
		['Total Infrastructure', r(s.totalInfrastructureCost)],
		[],
		['PROFESSIONAL FEES'],
		...(a.designSupervisionAED > 0 ? [['Design & Supervision (AED)', a.designSupervisionAED]] : []),
		...(a.projectMgmtAED > 0 ? [['Project Management (AED)', a.projectMgmtAED]] : []),
		...(a.otherProfessionalFeesAED > 0
			? [['Other Professional Fees (AED)', a.otherProfessionalFeesAED]]
			: []),
		['Total Professional Fees', r(s.totalProfessionalFees)],
		[],
		['SOFT COSTS'],
		['Total Soft Costs', r(s.totalSoftCost)],
		...(s.inflationOnCosts > 0 ? [['  Cost Inflation', r(s.inflationOnCosts)]] : []),
		[],
		['SALES & MARKETING'],
		[`Agent Commission (${a.agentCommissionPct}% of GDV)`, r(s.agentFees)],
		[`Marketing Budget (${a.marketingBudgetPct}% of GDV)`, r(s.marketingCost)],
		...(a.marketingLaunchAED > 0 ? [['Launch / Event Budget (AED)', a.marketingLaunchAED]] : []),
		['Total Sales Costs', r(s.totalSalesCost)],
		[],
		['FINANCE'],
		[`Loan Amount (${(a.debtToCostRatio * 100).toFixed(0)}% of pre-finance cost)`, r(s.debtAmount)],
		[`Interest (${a.financeRatePct}% p.a., ${s.interestOnlyMonths} months)`, r(s.totalInterest)],
		[`Arrangement Fee (${a.arrangementFeePct}%)`, r(s.arrangementFee)],
		...(a.hasVATBridgeLoan
			? [
					[
						`VAT Bridge Loan Interest (${a.vatBridgeLoanTermMonths}m @ ${a.vatBridgeLoanRatePct}%)`,
						r(s.vatBridgeLoanInterest)
					]
				]
			: []),
		['Total Finance Costs', r(s.totalFinanceCost)],
		[],
		['TOTAL DEVELOPMENT COST', r(s.totalDevCost)],
		['Gross Profit', r(s.grossProfit)],
		['Return on Cost', pct(s.profitOnCostPct)],
		[],
		['VAT MEMO (not in costs)'],
		[`VAT on Costs (${a.vatRateOnCostsPct}%)`, r(s.vatOnCosts)],
		[`VAT Recovery (${a.vatRecoveryPct}%)`, -r(s.vatRecovery)],
		['Net VAT Position', r(s.netVATPosition)],
		[],
		[`Corporate Tax (${a.corporateTaxRatePct}%)`, r(s.corporateTaxProvision)],
		['Net Profit (post-tax)', r(s.netProfit)]
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(devBudgetRows), 'Dev Budget');

	// ── Schedule ───────────────────────────────────────────────────────────────
	const scheduleRows: unknown[][] = [
		['Parameter', 'Value'],
		['Construction Period (months)', a.constructionMonths],
		['Sales Launch (month from start)', a.salesLaunchMonth],
		['Sales Duration (months)', a.salesMonths],
		['Capex Curve', a.capexDistributionCurve],
		['Total Quarters', s.totalQ],
		[],
		[
			'Quarter',
			'Land',
			'Construction',
			'Soft Costs',
			'Marketing',
			'Total Costs',
			'Revenue',
			'Net',
			'Cumulative'
		],
		...s.cashflow.map((p) => [
			`Q${p.q + 1}`,
			p.land ? r(p.land) : '',
			p.construction ? r(p.construction) : '',
			p.soft ? r(p.soft) : '',
			p.marketing ? r(p.marketing) : '',
			r(p.costs),
			p.revenue ? r(p.revenue) : '',
			r(p.net),
			r(p.cum)
		]),
		[],
		['Peak Funding Required (AED)', r(s.peakFunding)]
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(scheduleRows), 'Schedule');

	// ── Cash Flow ──────────────────────────────────────────────────────────────
	const cashFlowRows: unknown[][] = [
		[
			'Quarter',
			'Land',
			'Construction',
			'Soft Costs',
			'Selling & Mkt',
			'Total Outflows',
			a.useEscrowModel ? 'Escrow Release' : 'Sales Revenue',
			'Net Cash Flow',
			'Cumulative'
		],
		...s.cashflow.map((p) => [
			`Q${p.q + 1}`,
			p.land ? r(p.land) : '',
			p.construction ? r(p.construction) : '',
			p.soft ? r(p.soft) : '',
			p.marketing ? r(p.marketing) : '',
			r(p.costs),
			p.revenue ? r(p.revenue) : '',
			r(p.net),
			r(p.cum)
		]),
		[],
		['Peak Funding Required (AED)', r(s.peakFunding)],
		[
			'Cash Breakeven Quarter',
			s.cashBreakevenQuarter >= 0 ? `Q${s.cashBreakevenQuarter + 1}` : '—'
		],
		['Total Interest (AED)', r(s.totalInterest)]
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(cashFlowRows), 'Cash Flow');

	// ── Returns ────────────────────────────────────────────────────────────────
	const returnsRows: unknown[][] = [
		['Metric', 'Unlevered', 'Levered'],
		['Investment (AED)', r(s.totalDevCost), r(s.equityRequired)],
		['Net Revenue (AED)', r(s.netRevenue), r(s.netRevenue)],
		['Gross Profit (AED)', r(s.grossProfit), r(s.leveredProfit)],
		['Net Profit post-tax (AED)', r(s.netProfit), ''],
		['Profit on Cost', pct(s.profitOnCostPct), '—'],
		['Profit on GDV', pct(s.profitOnGDVPct), '—'],
		['Return on Equity', '—', pct(s.returnOnEquity)],
		['Equity Multiple', '—', `${s.equityMultiple.toFixed(2)}×`],
		['IRR (annualised)', irrFmt(s.unleveredIRR), irrFmt(s.leveredIRR)],
		[
			`NPV @ ${a.discountRatePct}% (AED)`,
			r(s.npvUnlevered),
			isFinite(s.npvLevered) ? r(s.npvLevered) : '—'
		],
		['Cash Payback', s.cashBreakevenQuarter >= 0 ? `Q${s.cashBreakevenQuarter + 1}` : '—', '—']
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(returnsRows), 'Returns');

	// ── Sources & Uses ─────────────────────────────────────────────────────────
	const totalDevCost = r(s.totalDevCost);
	const sourcesTotal = r(s.preHandoverGDV + s.debtAmount + s.equityRequired);
	const sourcesUsesRows: unknown[][] = [
		['SOURCES', '%', "AED '000"],
		[
			'Off-plan Proceeds',
			sourcesTotal > 0 ? pct((s.preHandoverGDV / sourcesTotal) * 100) : '—',
			fmtK(s.preHandoverGDV)
		],
		[
			'Senior Debt',
			sourcesTotal > 0 ? pct((s.debtAmount / sourcesTotal) * 100) : '—',
			fmtK(s.debtAmount)
		],
		[
			'Equity',
			sourcesTotal > 0 ? pct((s.equityRequired / sourcesTotal) * 100) : '—',
			fmtK(s.equityRequired)
		],
		['Total Sources', '100%', fmtK(s.preHandoverGDV + s.debtAmount + s.equityRequired)],
		[],
		['USES', '%', "AED '000"],
		[
			'Land Acquisition',
			totalDevCost > 0 ? pct((s.totalLandCost / totalDevCost) * 100) : '—',
			fmtK(s.totalLandCost)
		],
		[
			'Hard Construction',
			totalDevCost > 0 ? pct((s.totalHardCost / totalDevCost) * 100) : '—',
			fmtK(s.totalHardCost)
		],
		[
			'Soft Costs',
			totalDevCost > 0 ? pct((s.totalSoftCost / totalDevCost) * 100) : '—',
			fmtK(s.totalSoftCost)
		],
		[
			'Sales & Marketing',
			totalDevCost > 0 ? pct((s.totalSalesCost / totalDevCost) * 100) : '—',
			fmtK(s.totalSalesCost)
		],
		[
			'Finance Costs',
			totalDevCost > 0 ? pct((s.totalFinanceCost / totalDevCost) * 100) : '—',
			fmtK(s.totalFinanceCost)
		],
		...(s.vatBridgeLoanInterest > 0
			? [
					[
						'VAT Bridge Loan',
						totalDevCost > 0 ? pct((s.vatBridgeLoanInterest / totalDevCost) * 100) : '—',
						fmtK(s.vatBridgeLoanInterest)
					]
				]
			: []),
		['Total Uses', '100%', fmtK(s.totalDevCost)]
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(sourcesUsesRows), 'Sources & Uses');

	// ── Escrow (conditional) ───────────────────────────────────────────────────
	if (a.useEscrowModel && s.escrowData.length > 0) {
		const escrowRows: unknown[][] = [
			['RERA Escrow Milestones'],
			['Milestone', '% of Pre-HO GDV', 'Construction %', 'Quarter', "AED '000"],
			...a.escrowMilestones.map((m) => {
				const qIdx =
					m.constructionPct === 0
						? s.sq
						: Math.min(Math.floor((m.constructionPct / 100) * s.cq), s.totalQ - 1);
				return [
					m.name,
					pct(m.pct),
					pct(m.constructionPct),
					`Q${qIdx + 1}`,
					fmtK((m.pct / 100) * s.preHandoverGDV)
				];
			}),
			[],
			['Quarterly Escrow Flow'],
			['Quarter', 'Buyer Receipts', 'Developer Release', 'Escrow Float'],
			...s.escrowData
				.filter((d) => d.receipt > 0 || d.release > 0 || d.float > 0)
				.map((d) => [`Q${d.q + 1}`, fmtK(d.receipt), fmtK(d.release), fmtK(d.float)])
		];
		XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(escrowRows), 'Escrow');
	}

	// ── Assumptions ────────────────────────────────────────────────────────────
	const assumptionsRows: unknown[][] = [
		['Parameter', 'Value'],
		['LAND & SITE'],
		['Land Cost (AED)', a.landCost],
		['DLD Transfer Fee (%)', a.transferFeePct],
		['Site Area (sqm)', a.siteAreaSqm],
		['Plot Ratio / FAR', a.plotRatioFAR],
		['Loss Factor GFA→NSA (%)', a.lossFactorGFAtoNSA],
		['Has Demolition', a.hasDemolition ? 'Yes' : 'No'],
		[],
		['CONSTRUCTION'],
		['Build Cost/sqm (AED)', a.buildCostPerSqm],
		['Contingency (%)', a.contingencyPct],
		['Construction Period (months)', a.constructionMonths],
		['Capex Distribution Curve', a.capexDistributionCurve],
		['Mid-point Inflation (%)', a.midPointInflationPct],
		[],
		['INFRASTRUCTURE & AUTHORITY FEES'],
		['Infrastructure Works (AED)', a.infrastructureCostAED],
		['Authority Connection Fees (AED)', a.authorityConnectionFeesAED],
		['Community/Master-dev Fees (AED)', a.communityMasterDevFeesAED],
		['Demolition Cost (AED)', a.demolitionCostAED],
		[],
		['PROFESSIONAL FEES'],
		['Design & Supervision (AED)', a.designSupervisionAED],
		['Project Management (AED)', a.projectMgmtAED],
		['Other Professional Fees (AED)', a.otherProfessionalFeesAED],
		[],
		['SOFT COSTS (legacy %)'],
		['Soft Costs total (% of hard)', a.softCostsPct],
		['  Design & Engineering (%)', a.designFeePct],
		['  Project Management (%)', a.projectMgmtPct],
		[],
		['SALES & MARKETING'],
		['Sales Launch (months from start)', a.salesLaunchMonth],
		['Sales Duration (months)', a.salesMonths],
		['Agent Commission (% of GDV)', a.agentCommissionPct],
		['Marketing Budget (% of GDV)', a.marketingBudgetPct],
		['Marketing Launch Budget (AED)', a.marketingLaunchAED],
		['Presale Discount (%)', a.presaleDiscountPct],
		['Price Escalation p.a. (%)', a.priceEscalationPct],
		['Post-handover Unsold (%)', a.postHandoverSalesPct],
		[],
		['FINANCING'],
		['Debt-to-Cost Ratio (%)', +(a.debtToCostRatio * 100).toFixed(0)],
		['Interest Rate (% p.a.)', a.financeRatePct],
		['Arrangement Fee (%)', a.arrangementFeePct],
		['Interest-only Period (months)', s.interestOnlyMonths],
		['Has VAT Bridge Loan', a.hasVATBridgeLoan ? 'Yes' : 'No'],
		...(a.hasVATBridgeLoan
			? [
					['VAT Bridge Loan Term (months)', a.vatBridgeLoanTermMonths],
					['VAT Bridge Loan Rate (%)', a.vatBridgeLoanRatePct]
				]
			: []),
		[],
		['VAT & TAX'],
		['VAT Rate on Costs (%)', a.vatRateOnCostsPct],
		['VAT Recovery (%)', a.vatRecoveryPct],
		['Corporate Tax Rate (%)', a.corporateTaxRatePct],
		[],
		['RETAIL INCOME'],
		['Has Ancillary Retail', a.hasAncillaryRetail ? 'Yes' : 'No'],
		...(a.hasAncillaryRetail
			? [
					['Retail Area (sqm)', a.retailAreaSqm],
					['Retail Rent/sqm/yr (AED)', a.retailRentPerSqmYr],
					['Retail Yield / Cap Rate (%)', a.retailYieldCapRate]
				]
			: []),
		[],
		['ESCROW'],
		['Use RERA Escrow Model', a.useEscrowModel ? 'Yes' : 'No'],
		...(a.useEscrowModel
			? [['Off-plan Proceeds Used for Construction (%)', a.offPlanProceedsUsedForConstructionPct]]
			: []),
		[],
		['MACRO'],
		['Discount Rate (%)', a.discountRatePct],
		['Target ROC (%)', a.targetROCPct]
	];
	XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(assumptionsRows), 'Assumptions');

	// ── Download ───────────────────────────────────────────────────────────────
	const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' });
	const blob = new Blob([buf], {
		type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
	});
	const url = URL.createObjectURL(blob);
	const anchor = document.createElement('a');
	anchor.href = url;
	anchor.download = `feasibility_${Date.now()}.xlsx`;
	anchor.click();
	URL.revokeObjectURL(url);
}
