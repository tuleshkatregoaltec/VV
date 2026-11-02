<script lang="ts">
/**
 * Confirm before deleting a conversation. Styled with the CRM theme tokens so it follows light
 * and dark mode (the shared ConfirmModal is always white).
 */
let {
	open,
	ondelete,
	oncancel,
	title = 'Delete conversation?',
	confirmText = 'Delete'
}: {
	open: boolean
	ondelete: () => void
	oncancel: () => void
	title?: string
	confirmText?: string
} = $props()

function onkeydown(event: KeyboardEvent) {
	if (event.key === 'Escape' && open) oncancel()
}
</script>

<svelte:window {onkeydown} />

{#if open}
	<div
		class="delete-backdrop"
		role="presentation"
		onclick={(e) => {
			if (e.target === e.currentTarget) oncancel()
		}}
	>
		<div class="delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-title">
			<h3 id="delete-title">{title}</h3>
			<p>This removes the conversation. Changes you already confirmed stay on the leads.</p>
			<div class="actions">
				<button type="button" class="btn ghost" onclick={oncancel}>Cancel</button>
				<button type="button" class="btn danger" onclick={ondelete}>{confirmText}</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.delete-backdrop {
		position: fixed;
		inset: 0;
		z-index: 60;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 16px;
		background: var(--scrim);
	}
	.delete-dialog {
		width: 100%;
		max-width: 420px;
		background: var(--card);
		color: var(--text);
		border: 1px solid var(--sep);
		border-radius: 12px;
		box-shadow: var(--shadow-lg);
		padding: 20px;
	}
	h3 {
		margin: 0 0 8px;
		font-size: 16px;
		font-weight: 600;
		color: var(--text);
	}
	p {
		margin: 0;
		font-size: 14px;
		color: var(--text2);
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 20px;
	}
</style>
