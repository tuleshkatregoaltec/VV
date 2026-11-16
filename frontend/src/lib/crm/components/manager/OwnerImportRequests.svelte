<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crm } from '../../api'
import type { Tone } from '../../api/types'
import { personName } from '../../assignment'
import { fmt, fullDate } from '../../format'
import { crmQueries } from '../../queries'
import { write } from '../../write'
import Chip from '../ui/Chip.svelte'
import QueryView from '../ui/QueryView.svelte'

/**
 * Owner files agents sent for approval. A manager sees their teams' requests (an administrator
 * everyone's) and approves or rejects them; an agent follows their own. The server decides who
 * may decide; a manager never sees the buttons on a file they cannot decide.
 */
const scope = createQuery(() => crmQueries.assignmentScope())
const requests = createQuery(() => crmQueries.ownerImportRequests())
const canDecide = $derived(scope.data?.capabilities.can_assign ?? false)
let busy = $state<number | null>(null)

const STATUS: Record<string, { label: string; tone: Tone }> = {
	pending: { label: 'Waiting for approval', tone: 'amber' },
	queued: { label: 'Queued for import', tone: 'blue' },
	processing: { label: 'Importing…', tone: 'blue' },
	approved: { label: 'Approved and imported', tone: 'green' },
	rejected: { label: 'Rejected', tone: 'neutral' },
	failed: { label: 'Import failed', tone: 'red' }
}

async function decide(id: number, decision: 'approve' | 'reject') {
	busy = id
	await write({
		call: () => crm.imports.decideOwnerRequest(id, decision),
		success: ({ data }) =>
			data.status === 'approved'
				? 'Approved and imported'
				: data.status === 'queued'
					? 'Approved and queued for import'
					: data.status === 'rejected'
						? 'Rejected'
						: (data.error_message ?? null),
		undoable: false,
		event: 'import_requested'
	})
	busy = null
}
</script>

<QueryView query={requests} rows={1}>
	{#snippet children(list)}
		{#if list.length}
			<div class="tblwrap">
				<table class="tbl">
					<caption class="sr-only">Owner files waiting for a manager's approval</caption>
					<thead>
						<tr><th>File</th><th>Sent by</th><th>Sent</th><th>Status</th><th><span class="sr-only">Actions</span></th></tr>
					</thead>
					<tbody>
						{#each list as r (r.id)}
							{@const status = STATUS[r.status] ?? STATUS.pending}
							<tr>
								<td class="nm mono">{r.original_filename} <span class="sub">· {fmt(Math.ceil(r.size_bytes / 1024))} KB</span></td>
								<td data-label="Sent by">{personName(scope.data, r.requested_by_user_id)}</td>
								<td class="sub" data-label="Sent">{fullDate(r.created_at.slice(0, 10))}</td>
								<td data-label="Status">
									<Chip tone={status.tone}>{status.label}</Chip>
									{#if r.error_message}<div class="small muted">{r.error_message}</div>{/if}
								</td>
								<td class="acts">
									{#if canDecide && (r.status === 'pending' || r.status === 'failed')}
										<button
											type="button"
											class="btn sm"
											disabled={busy !== null}
											aria-label={`Approve ${r.original_filename}`}
											onclick={() => decide(r.id, 'approve')}
										>
											{busy === r.id ? 'Working…' : r.status === 'failed' ? 'Try again' : 'Approve'}
										</button>
										{#if r.status === 'pending'}
											<button
												type="button"
												class="btn ghost sm"
												disabled={busy !== null}
												aria-label={`Reject ${r.original_filename}`}
												onclick={() => decide(r.id, 'reject')}
											>
												Reject
											</button>
										{/if}
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/snippet}
</QueryView>

<style>
	.acts {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		justify-content: flex-end;
	}
</style>
