<script lang="ts">
	let {
		open = false,
		title,
		message,
		confirmText = 'Confirm',
		cancelText = 'Cancel',
		confirmVariant = 'danger',
		onConfirm,
		onCancel
	}: {
		open: boolean;
		title: string;
		message: string;
		confirmText?: string;
		cancelText?: string;
		confirmVariant?: 'danger' | 'primary';
		onConfirm: () => void;
		onCancel: () => void;
	} = $props();

	// Handle ESC key
	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape' && open) {
			onCancel();
		}
	}

	// Handle backdrop click
	function handleBackdropClick(event: MouseEvent) {
		if (event.target === event.currentTarget) {
			onCancel();
		}
	}

	// Prevent body scroll when modal is open
	$effect(() => {
		if (open) {
			document.body.style.overflow = 'hidden';
		} else {
			document.body.style.overflow = '';
		}

		return () => {
			document.body.style.overflow = '';
		};
	});

	const confirmButtonClasses =
		confirmVariant === 'danger'
			? 'bg-red-600 hover:bg-red-700 text-white'
			: 'bg-primary hover:bg-primary-dark text-white';
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
		onclick={handleBackdropClick}
		role="presentation"
	>
		<div
			class="bg-white rounded-lg shadow-xl w-full max-w-md"
			role="dialog"
			aria-modal="true"
			aria-labelledby="confirm-title"
		>
			<!-- Header -->
			<div class="px-6 py-4 border-b border-gray-200">
				<h3 id="confirm-title" class="text-lg font-semibold text-gray-900">{title}</h3>
			</div>

			<!-- Content -->
			<div class="px-6 py-4">
				<p class="text-gray-600">{message}</p>
			</div>

			<!-- Actions -->
			<div class="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
				<button
					onclick={onCancel}
					class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition"
				>
					{cancelText}
				</button>
				<button
					onclick={onConfirm}
					class="px-4 py-2 text-sm font-medium rounded-lg transition {confirmButtonClasses}"
				>
					{confirmText}
				</button>
			</div>
		</div>
	</div>
{/if}
