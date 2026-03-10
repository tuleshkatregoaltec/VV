<script lang="ts">
let {
	placeholder = 'Ask me anything about Dubai real estate...',
	onSubmit,
	disabled = false
}: {
	placeholder?: string
	onSubmit: (message: string) => void
	disabled?: boolean
} = $props()

let inputValue = $state('')
let isFocused = $state(false)
let textareaRef = $state<HTMLTextAreaElement>()
let isSubmitting = $state(false)
let error = $state<string | null>(null)

function handleFocus() {
	isFocused = true
	error = null
}

function handleBlur() {
	// Only collapse if input is empty
	if (!inputValue.trim()) {
		isFocused = false
	}
}

function autoResize() {
	if (textareaRef) {
		textareaRef.style.height = 'auto'
		const newHeight = Math.min(textareaRef.scrollHeight, 200)
		textareaRef.style.height = `${newHeight}px`
	}
}

async function handleSubmit() {
	const text = inputValue.trim()
	if (!text || disabled || isSubmitting) return

	try {
		isSubmitting = true
		error = null
		await onSubmit(text)
		// Clear input after successful submission
		inputValue = ''
		isFocused = false
		if (textareaRef) textareaRef.style.height = 'auto'
	} catch (err) {
		error = err instanceof Error ? err.message : 'Failed to submit message'
		isSubmitting = false
	}
}

function handleKeyDown(e: KeyboardEvent) {
	if (e.key === 'Enter' && !e.shiftKey) {
		e.preventDefault()
		handleSubmit()
	}
}
</script>

<div class="w-full flex justify-center px-4 animate-fade-in">
	<div class="w-full max-w-2xl">
		<div class="relative transition-all duration-300 ease-in-out">
			<div
				class="relative bg-white border rounded-2xl transition-all duration-300 {isFocused
					? 'border-teal-600/40 shadow-lg'
					: 'border-slate-300 shadow-sm hover:shadow-md hover:border-slate-400'}"
			>
				<textarea
					bind:this={textareaRef}
					bind:value={inputValue}
					onfocus={handleFocus}
					onblur={handleBlur}
					oninput={autoResize}
					onkeydown={handleKeyDown}
					{placeholder}
					disabled={disabled || isSubmitting}
					rows="1"
					class="w-full px-5 py-3.5 bg-transparent resize-none outline-none text-slate-800 placeholder-slate-400 rounded-2xl pr-14 flex items-center"
					style="min-height: 52px; max-height: 200px; line-height: 1.5;"
				></textarea>

				<!-- Send Button -->
				<button
					onclick={handleSubmit}
					disabled={!inputValue.trim() || disabled || isSubmitting}
					class="absolute right-3 top-1/2 -translate-y-1/2 p-2.5 rounded-full transition-all duration-200 {inputValue.trim() &&
					!disabled &&
					!isSubmitting
						? 'bg-primary text-white hover:bg-primary-dark shadow-md opacity-100'
						: 'bg-slate-200 text-slate-400 opacity-50 cursor-not-allowed'}"
					aria-label="Send message"
				>
					{#if isSubmitting}
						<svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
							<circle
								class="opacity-25"
								cx="12"
								cy="12"
								r="10"
								stroke="currentColor"
								stroke-width="4"
							></circle>
							<path
								class="opacity-75"
								fill="currentColor"
								d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
							></path>
						</svg>
					{:else}
						<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
							<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"></path>
						</svg>
					{/if}
				</button>
			</div>

			<!-- Error Message -->
			{#if error}
				<div
					class="mt-2 px-4 py-2 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm animate-fade-in"
				>
					{error}
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	@keyframes fade-in {
		from {
			opacity: 0;
			transform: translateY(10px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	.animate-fade-in {
		animation: fade-in 0.3s ease-out;
	}

	/* Ensure smooth scrollbar when content overflows */
	textarea::-webkit-scrollbar {
		width: 6px;
	}

	textarea::-webkit-scrollbar-track {
		background: transparent;
	}

	textarea::-webkit-scrollbar-thumb {
		background: rgba(0, 0, 0, 0.2);
		border-radius: 3px;
	}

	textarea::-webkit-scrollbar-thumb:hover {
		background: rgba(0, 0, 0, 0.3);
	}
</style>
