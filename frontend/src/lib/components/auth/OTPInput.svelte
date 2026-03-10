<script lang="ts">
interface Props {
	value: string
	length?: number
	error?: string
	disabled?: boolean
	onComplete?: (code: string) => void
}

let {
	value = $bindable(''),
	length = 6,
	error = '',
	disabled = false,
	onComplete
}: Props = $props()

let inputs: HTMLInputElement[] = []
let digits = $state(Array(length).fill(''))

$effect(() => {
	if (value.length === 0) {
		digits = Array(length).fill('')
	}
})

function handleInput(index: number, event: Event) {
	const input = event.target as HTMLInputElement
	const val = input.value

	if (val.length > 1) {
		input.value = val[0]
	}

	digits[index] = input.value
	value = digits.join('')

	if (input.value && index < length - 1) {
		inputs[index + 1]?.focus()
	}

	if (value.length === length && onComplete) {
		onComplete(value)
	}
}

function handleKeyDown(index: number, event: KeyboardEvent) {
	if (event.key === 'Backspace' && !digits[index] && index > 0) {
		inputs[index - 1]?.focus()
	} else if (event.key === 'ArrowLeft' && index > 0) {
		event.preventDefault()
		inputs[index - 1]?.focus()
	} else if (event.key === 'ArrowRight' && index < length - 1) {
		event.preventDefault()
		inputs[index + 1]?.focus()
	}
}

function handlePaste(event: ClipboardEvent) {
	event.preventDefault()
	const pastedData = event.clipboardData?.getData('text') || ''
	const pastedDigits = pastedData.replace(/\D/g, '').slice(0, length)

	for (let i = 0; i < pastedDigits.length; i++) {
		digits[i] = pastedDigits[i]
		if (inputs[i]) {
			inputs[i].value = pastedDigits[i]
		}
	}

	value = digits.join('')

	const nextEmptyIndex = pastedDigits.length < length ? pastedDigits.length : length - 1
	inputs[nextEmptyIndex]?.focus()

	if (value.length === length && onComplete) {
		onComplete(value)
	}
}
</script>

<div class="w-full">
	<div class="flex gap-2 justify-center">
		{#each Array(length) as _, i (`otp-${i}`)}
			<input
				bind:this={inputs[i]}
				type="text"
				inputmode="numeric"
				maxlength="1"
				{disabled}
				oninput={(e) => handleInput(i, e)}
				onkeydown={(e) => handleKeyDown(i, e)}
				onpaste={i === 0 ? handlePaste : undefined}
				class="w-12 h-14 text-center text-2xl font-semibold bg-gray-50 border rounded-lg
                       transition-all focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20
                       disabled:bg-gray-100 disabled:cursor-not-allowed
                       {error ? 'border-red-300 bg-red-50' : 'border-gray-200'}"
			/>
		{/each}
	</div>
	{#if error}
		<p class="mt-3 text-sm text-red-600 text-center">{error}</p>
	{/if}
</div>
