<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { browser } from '$app/environment'
import type { ProjectSearchItem } from '$lib/api/analytics'
import { analyticsQueries } from '$lib/queries/analytics'
import AnalyticsError from './AnalyticsError.svelte'

let {
	value = $bindable<ProjectSearchItem | null>(null),
	placeholder = 'Search building, project or area...',
	label = 'Location',
	onSelect
}: {
	value?: ProjectSearchItem | null
	label?: string
	placeholder?: string
	onSelect?: (project: ProjectSearchItem | null) => void
} = $props()

const listId = $props.id()
let inputValue = $state('')
$effect(() => {
	inputValue = value?.filter_type === 'market' ? '' : (value?.name ?? '')
})
let isOpen = $state(false)
let container: HTMLDivElement
let input: HTMLInputElement
const searchTerm = $derived(inputValue.trim())
let debouncedSearch = $state('')
$effect(() => {
	const term = searchTerm
	const timer = setTimeout(() => (debouncedSearch = term), 250)
	return () => clearTimeout(timer)
})

function clickOutside(node: HTMLElement, callback: () => void) {
	function handle(e: MouseEvent) {
		if (!node.contains(e.target as Node)) callback()
	}
	document.addEventListener('mousedown', handle, true)
	return {
		destroy() {
			document.removeEventListener('mousedown', handle, true)
		}
	}
}

const projectsQuery = createQuery(() => ({
	...analyticsQueries.projectSearch(debouncedSearch, 50),
	enabled: browser && isOpen
}))

const filtered = $derived(projectsQuery.data?.projects ?? [])

function select(project: ProjectSearchItem) {
	value = project
	inputValue = project.name
	input.focus()
	isOpen = false
	onSelect?.(project)
}

function clear() {
	value = null
	inputValue = ''
	isOpen = false
	onSelect?.(null)
}

function handleKeydown(e: KeyboardEvent) {
	if (e.key === 'Escape') {
		input.focus()
		isOpen = false
	}
	if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
		e.preventDefault()
		const options = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="option"]'))
		const current = options.indexOf(document.activeElement as HTMLButtonElement)
		const next =
			e.key === 'ArrowDown'
				? (current + 1) % options.length
				: current <= 0
					? options.length - 1
					: current - 1
		options[next]?.focus()
	}
	if (e.key === 'Enter' && e.target === input) {
		e.preventDefault()
		if (searchTerm === debouncedSearch && !projectsQuery.isFetching && filtered.length > 0)
			select(filtered[0])
	}
}
</script>

<div class="relative" bind:this={container} role="group" aria-label={label}
	onfocusout={(event) => { if (!container.contains(event.relatedTarget as Node)) isOpen = false }}
	use:clickOutside={() => (isOpen = false)}>
	<div class="relative">
		<div class="pointer-events-none absolute inset-y-0 left-3 flex items-center">
			<svg class="h-4 w-4 text-fg-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
			</svg>
		</div>
		<input
			type="text"
			class="ui-field w-full py-2 pl-9 pr-8 text-sm"
			{placeholder}
			aria-label={label}
			bind:this={input}
			role="combobox"
			aria-autocomplete="list"
			aria-controls={isOpen ? listId : undefined}
			onkeydown={handleKeydown}
			aria-expanded={isOpen}
			aria-haspopup="listbox"
			bind:value={inputValue}
			oninput={() => (isOpen = true)}
			onfocus={() => (isOpen = true)}
		/>
		{#if value && value.filter_type !== 'market'}
			<button
				type="button"
				class="absolute inset-y-0 right-2 flex items-center px-1 text-fg-5 hover:text-fg-2"
				onclick={clear}
				onkeydown={handleKeydown}
				aria-label="Clear selection"
			>
				<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		{/if}
	</div>

	{#if isOpen}
		<div id={listId} role="listbox" aria-label={`${label} results`} tabindex="-1" class="ui-menu absolute z-50 mt-2 max-h-72 w-full overflow-y-auto p-1.5">
			{#if projectsQuery.isLoading || searchTerm !== debouncedSearch}
				<div class="px-3 py-2 text-sm text-fg-5">Loading...</div>
			{:else if projectsQuery.isError}
				<AnalyticsError message="Failed to load projects." retry={() => { input.focus(); return projectsQuery.refetch() }} fetching={projectsQuery.isFetching} />
			{:else if filtered.length === 0}
				<div class="px-3 py-2 text-sm text-fg-5">No projects found</div>
			{:else}
				{#each filtered as project}
					<button
						type="button"
						class="w-full rounded-md px-3 py-2 text-left text-sm transition-colors {project.name ===
						value?.name
							? 'bg-info-bg font-medium text-info'
							: 'text-fg-2 hover:bg-panel hover:text-fg-1'}"
						onclick={() => select(project)}
						onkeydown={handleKeydown}
						role="option"
						aria-selected={value?.name === project.name && value?.filter_type === project.filter_type}
					>
						<span>{project.name}</span>
						<span class="ml-2 text-xs text-fg-4">{project.scope_kind ?? 'Location'}</span>
					</button>
				{/each}
			{/if}
		</div>
	{/if}
</div>
