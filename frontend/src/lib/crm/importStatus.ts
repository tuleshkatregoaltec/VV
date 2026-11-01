import type { ImportStatus, OwnerImportResult } from './api/types'
import { fmt } from './format'

export const IMPORT_STATUS = {
	queued: { label: 'Queued', tone: 'amber' },
	retry_wait: { label: 'Waiting to retry', tone: 'amber' },
	processing: { label: 'Processing', tone: 'amber' },
	completed: { label: 'Completed', tone: 'green' },
	failed: { label: 'Failed', tone: 'red' }
} as const

export function importIsActive(status: ImportStatus): boolean {
	return status === 'queued' || status === 'retry_wait' || status === 'processing'
}

/** Poll quickly at first, then back off to at most one read per minute until terminal. */
export function importPollInterval(active: boolean, updates = 0): number | false {
	return active ? Math.min(5000 * 2 ** Math.min(Math.max(updates - 1, 0), 4), 60000) : false
}

export function importProgressNotice(status: ImportStatus): string {
	if (status === 'queued')
		return 'This file is queued. You can close this panel; processing continues in the background.'
	if (status === 'retry_wait')
		return 'This file is waiting to retry. Processing will resume automatically.'
	return 'This file is being imported. Counts appear when it finishes; you can close this panel.'
}

/** A reused active job is not a completed import, and accepted uploads have no row results yet. */
export function ownerImportNotice(result: OwnerImportResult): string | null {
	if (!result.alreadyImported) return null
	return result.status === 'completed'
		? `This file was already imported as “${result.name}”. Nothing new was added.`
		: `This file already has an import recorded as “${result.name}”.`
}

export function importUploadMessage(
	status: ImportStatus,
	rows: number,
	reused = false
): string | null {
	if (status === 'completed') return reused ? null : `Imported · ${fmt(rows)} rows`
	if (status === 'failed') return 'The import failed. Check its status before trying again.'
	if (reused) return 'This file already has an import in progress.'
	if (status === 'queued') return 'Import queued'
	return status === 'retry_wait'
		? 'Import accepted · waiting to retry'
		: 'Import accepted · processing in the background'
}
