<script lang="ts">
interface Props {
	label: string
	type?: string
	value: string
	placeholder?: string
	error?: string
	disabled?: boolean
	required?: boolean
	autocomplete?: 'off' | 'on' | 'email' | 'username' | 'given-name' | 'family-name' | 'name'
	id?: string
}

let {
	label,
	type = 'text',
	value = $bindable(''),
	placeholder = '',
	error = '',
	disabled = false,
	required = false,
	autocomplete = 'off',
	id = `input-${Math.random().toString(36).substring(2, 11)}`
}: Props = $props()
</script>

<div class="w-full">
	<label for={id} class="mb-2 block text-sm font-medium text-[var(--color-fg-1)]">
		{label}
		{#if required}
			<span class="text-[var(--color-error)]">*</span>
		{/if}
	</label>
	<input
		{id}
		{type}
		bind:value
		{placeholder}
		{disabled}
		{required}
		{autocomplete}
		class="w-full rounded-md border bg-white px-3.5 py-3 text-sm text-[var(--color-fg-1)] placeholder-[var(--color-fg-5)] transition-all
               focus:outline-none focus:border-[var(--color-navy-900)] focus:ring-2 focus:ring-[rgba(11,27,43,0.12)]
               disabled:cursor-not-allowed disabled:bg-slate-100
               {error
			? 'border-[var(--color-error)] bg-[var(--color-error-bg)]'
			: 'border-[var(--color-border)]'}"
	/>
	{#if error}
		<p class="mt-2 text-sm text-[var(--color-error)]">{error}</p>
	{/if}
</div>
