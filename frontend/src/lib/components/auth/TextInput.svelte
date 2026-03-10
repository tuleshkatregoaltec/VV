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
	<label for={id} class="block text-sm font-medium text-gray-700 mb-2">
		{label}
		{#if required}
			<span class="text-red-500">*</span>
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
		class="w-full px-4 py-3 bg-gray-50 border rounded-lg transition-all
               focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20
               disabled:bg-gray-100 disabled:cursor-not-allowed
               {error ? 'border-red-300 bg-red-50' : 'border-gray-200'}"
	/>
	{#if error}
		<p class="mt-2 text-sm text-red-600">{error}</p>
	{/if}
</div>
