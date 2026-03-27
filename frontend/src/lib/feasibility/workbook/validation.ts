// ══════════════════════════════════════════════════════════════════════════════
// Workbook Validation — Separate validation checks
// ══════════════════════════════════════════════════════════════════════════════
// Validates workbook outputs and assumptions, returns issues.
// ══════════════════════════════════════════════════════════════════════════════

import type { WorkbookOutputs } from './engine'
import type { FeasibilityAssumptions } from './models'

export type ValidationSeverity = 'hard_fail' | 'warning' | 'missing_evidence'
export type ValidationStatus = 'ready' | 'needs_review' | 'invalid'

export interface ValidationIssue {
	code: string
	severity: ValidationSeverity
	message: string
	field?: string
}

export interface ValidationResult {
	status: ValidationStatus
	hardFailures: number
	warnings: number
	missingEvidence: number
	issues: ValidationIssue[]
}

export function validateWorkbook(
	assumptions: FeasibilityAssumptions,
	outputs: WorkbookOutputs
): ValidationResult {
	const issues: ValidationIssue[] = []

	// Check for missing unit mix
	if (outputs.program.totalUnits === 0) {
		issues.push({
			code: 'no_units',
			severity: 'warning',
			message: 'No unit mix configured',
			field: 'unitConfigs'
		})
	}

	// Check for zero revenue
	if (outputs.program.grossRevenueAed === 0 && outputs.program.totalUnits > 0) {
		issues.push({
			code: 'zero_revenue',
			severity: 'warning',
			message: 'Revenue is zero despite having units',
			field: 'unitConfigs'
		})
	}

	// Check funding gap
	if (Math.abs(outputs.funding.gapAed) > 1000) {
		issues.push({
			code: 'funding_gap',
			severity: outputs.funding.gapAed > 0 ? 'hard_fail' : 'warning',
			message: `Funding gap of AED ${Math.round(outputs.funding.gapAed).toLocaleString()}`,
			field: 'funding'
		})
	}

	// Check negative margin
	if (outputs.returns.grossMarginPct < 0) {
		issues.push({
			code: 'negative_margin',
			severity: 'hard_fail',
			message: 'Project has negative gross margin',
			field: 'returns'
		})
	}

	// Check for missing land cost
	if (
		outputs.costs.landAcquisitionAed === 0 &&
		assumptions.landPricePsqm === 0 &&
		!assumptions.landAcquisitionCostOverrideAed
	) {
		issues.push({
			code: 'missing_land_cost',
			severity: 'missing_evidence',
			message: 'Land acquisition cost not set',
			field: 'landPricePsqm'
		})
	}

	// Check for missing construction cost
	if (
		outputs.costs.constructionCostAed === 0 &&
		assumptions.constructionCostPsqmBua === 0 &&
		!assumptions.constructionCostOverrideAed
	) {
		issues.push({
			code: 'missing_construction_cost',
			severity: 'missing_evidence',
			message: 'Construction cost not set',
			field: 'constructionCostPsqmBua'
		})
	}

	const hardFailures = issues.filter((i) => i.severity === 'hard_fail').length
	const warnings = issues.filter((i) => i.severity === 'warning').length
	const missingEvidence = issues.filter((i) => i.severity === 'missing_evidence').length

	let status: ValidationStatus = 'ready'
	if (hardFailures > 0) {
		status = 'invalid'
	} else if (warnings > 0 || missingEvidence > 0) {
		status = 'needs_review'
	}

	return {
		status,
		hardFailures,
		warnings,
		missingEvidence,
		issues
	}
}
