<script lang="ts">
import type { Snippet } from 'svelte'

let {
	open = false,
	onClose,
	title,
	size = 'lg',
	children
}: {
	open: boolean
	onClose: () => void
	title: string
	size?: 'md' | 'lg' | 'xl'
	children?: Snippet
} = $props()

let dialog: HTMLDivElement | undefined

function focusableElements(node: HTMLDivElement) {
	return Array.from(
		node.querySelectorAll<HTMLElement>(
			'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
		)
	).filter((element) => element.getClientRects().length > 0)
}

function manageFocus(node: HTMLDivElement) {
	const previous = document.activeElement
	dialog = node
	;(focusableElements(node)[0] ?? node).focus()
	return {
		destroy() {
			dialog = undefined
			if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
		}
	}
}

// Keep keyboard navigation inside the open dialog.
function handleKeydown(event: KeyboardEvent) {
	if (event.key === 'Escape' && open) {
		event.preventDefault()
		onClose()
	}
	if (event.key === 'Tab' && open && dialog) {
		const elements = focusableElements(dialog)
		const first = elements[0] ?? dialog
		const last = elements.at(-1) ?? dialog
		if (
			!dialog.contains(document.activeElement) ||
			(event.shiftKey && document.activeElement === first) ||
			(!event.shiftKey && document.activeElement === last)
		) {
			event.preventDefault()
			;(event.shiftKey ? last : first).focus()
		}
	}
}

// Handle backdrop click
function handleBackdropClick(event: MouseEvent) {
	if (event.target === event.currentTarget) {
		onClose()
	}
}

// Prevent body scroll when modal is open
$effect(() => {
	if (!open) return
	const previousOverflow = document.body.style.overflow
	document.body.style.overflow = 'hidden'
	return () => {
		document.body.style.overflow = previousOverflow
	}
})

const sizeClasses = {
	md: 'max-w-2xl',
	lg: 'max-w-4xl',
	xl: 'max-w-6xl'
}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50  animate-fade-in"
		onclick={handleBackdropClick}
		role="presentation"
	>
		<div
			class="bg-card rounded-lg border border-border shadow-xl w-full {sizeClasses[
				size
			]} max-h-[90vh] overflow-hidden animate-scale-in"
			use:manageFocus
			tabindex="-1"
			role="dialog"
			aria-modal="true"
			aria-labelledby="modal-title"
		>
			<!-- Header -->
			<div
				class="flex items-center justify-between px-6 py-4 border-b border-border bg-card"
			>
				<h2 id="modal-title" class="text-2xl font-semibold text-fg-1">{title}</h2>
				<button
					onclick={onClose}
					class="p-2 rounded-lg hover:bg-panel transition-colors"
					aria-label="Close modal"
				>
					<svg class="w-6 h-6 text-fg-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M6 18L18 6M6 6l12 12"
						/>
					</svg>
				</button>
			</div>

			<!-- Content -->
			<div class="overflow-y-auto max-h-[calc(90vh-80px)] px-6 py-6">
				{@render children?.()}
			</div>
		</div>
	</div>
{/if}

<style>
	@keyframes fade-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	@keyframes scale-in {
		from {
			opacity: 0;
			transform: scale(0.95);
		}
		to {
			opacity: 1;
			transform: scale(1);
		}
	}

	.animate-fade-in {
		animation: fade-in 0.2s ease-out;
	}

	.animate-scale-in {
		animation: scale-in 0.2s ease-out;
	}
</style>
