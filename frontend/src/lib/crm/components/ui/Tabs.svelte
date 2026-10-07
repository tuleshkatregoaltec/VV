<script module lang="ts">
export interface TabItem<V> {
	id: V
	label: string
	count?: number | null
}
</script>

<script lang="ts" generics="T extends string">
	let {
		items,
		value,
		onselect,
		label,
		variant = 'page'
	}: {
		items: TabItem<T>[]
		value: T | ''
		onselect: (id: T) => void
		label: string
		variant?: 'page' | 'card' | 'panel'
	} = $props()

	const cls = $derived(variant === 'card' ? 'cardtabs' : variant === 'panel' ? 'dtabs' : 'tabs')

	function onkeydown(e: KeyboardEvent, i: number) {
		if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
		e.preventDefault()
		const next = (i + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length
		onselect(items[next].id)
		const tabs = (e.currentTarget as HTMLElement).parentElement?.querySelectorAll('button')
		tabs?.[next]?.focus()
	}
</script>

<div class={cls} role="tablist" aria-label={label}>
	{#each items as item, i (item.id)}
		<button
			type="button"
			class="tab"
			role="tab"
			aria-selected={value === item.id}
			tabindex={value === item.id || (value === '' && i === 0) ? 0 : -1}
			onclick={() => onselect(item.id)}
			onkeydown={(e) => onkeydown(e, i)}
		>
			{item.label}
			{#if item.count !== undefined && item.count !== null}<span class="ct">{item.count}</span>{/if}
		</button>
	{/each}
</div>
