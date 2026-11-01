import type { ImportRequest } from '../api/types'
import { onCrmIdentityChange } from '../identity.svelte'

/** Session-only watch list; reopening import history resumes polling after a page reload. */
export const pendingImports = $state({ ids: [] as string[] })

export function watchQueuedImport(id: string): void {
	if (!pendingImports.ids.includes(id)) pendingImports.ids.push(id)
}

/** Only a fresh history response can end a watch; cached pre-upload data cannot stop it. */
export function settleQueuedImports(jobs: ImportRequest[]): void {
	const terminal = new Set(
		jobs
			.filter((job) => job.jobStatus === 'completed' || job.jobStatus === 'failed')
			.map((job) => job.id)
	)
	pendingImports.ids = pendingImports.ids.filter((id) => !terminal.has(id))
}

onCrmIdentityChange(() => {
	pendingImports.ids = []
})
