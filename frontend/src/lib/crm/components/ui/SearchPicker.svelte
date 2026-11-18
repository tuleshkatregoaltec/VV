<script lang="ts">
import type Building from 'lucide-svelte/icons/building-2'
import Check from 'lucide-svelte/icons/check'
import ChevronDown from 'lucide-svelte/icons/chevron-down'
import Search from 'lucide-svelte/icons/search'
import { tick } from 'svelte'
import { fmt } from '../../format'

/**
 * A picker button for long lists (Property Finder companies, a company's agents): an in-page menu
 * like FilterMenu (native selects do not show in a screen share) with a search box on top.
 * Typing filters by label and meta; ↓ moves into the list, ↑ ↓ Home End move, Enter picks, Escape closes.
 */
let {
	label,
	icon: Icon,
	options,
	value,
	onselect,
	allLabel,
	allMeta,
	noun,
	disabled = false,
	block = false
}: {
	/** Small line above the value ("Property Finder company"). */
	label: string
	/** A lucide icon, e.g. building-2 or users. */
	icon: typeof Building
	options: { id: string; label: string; meta?: string }[]
	value: string
	onselect: (id: string) => void
	/** The "no filter" row ("All companies"), value ''. */
	allLabel: string
	allMeta?: string
	/** Plural for the search box ("companies"). */
	noun: string
	disabled?: boolean
	/** Fill the row, e.g. as a form field. */
	block?: boolean
} = $props()

/** Rows drawn at once; typing narrows the rest. */
const SHOWN = 200

let open = $state(false)
let query = $state('')
let btn: HTMLButtonElement | undefined = $state()
let menu: HTMLDivElement | undefined = $state()
let input: HTMLInputElement | undefined = $state()

const current = $derived(options.find((o) => o.id === value))
const matches = $derived.by(() => {
	const q = query.trim().toLocaleLowerCase()
	return q
		? options.filter((o) => `${o.label} ${o.meta ?? ''}`.toLocaleLowerCase().includes(q))
		: options
})
const shown = $derived(matches.slice(0, SHOWN))

async function show() {
	open = true
	query = ''
	await tick()
	input?.focus()
}

function close(focusButton = false) {
	open = false
	if (focusButton) btn?.focus()
}

function pick(id: string) {
	if (id !== value) onselect(id)
	close(true)
}

const rows = () => [...(menu?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? [])]

function oninputkey(e: KeyboardEvent) {
	if (e.key === 'ArrowDown') {
		e.preventDefault()
		rows()[0]?.focus()
	} else if (e.key === 'Enter') {
		e.preventDefault()
		const first = shown[0]
		if (query.trim() && first) pick(first.id)
	} else if (e.key === 'Escape') {
		e.stopPropagation()
		close(true)
	}
}

function onlistkey(e: KeyboardEvent) {
	const items = rows()
	const i = items.indexOf(document.activeElement as HTMLButtonElement)
	if (i < 0) return
	const go = (n: number) => items[Math.max(0, Math.min(items.length - 1, n))]?.focus()
	if (e.key === 'ArrowDown') go(i + 1)
	else if (e.key === 'ArrowUp') {
		// Up from the first row goes back to the search box.
		if (i === 0) input?.focus()
		else go(i - 1)
	} else if (e.key === 'Home') go(0)
	else if (e.key === 'End') go(items.length - 1)
	else if (e.key === 'Escape') {
		e.stopPropagation()
		close(true)
	} else if (e.key === 'Tab') {
		close()
		return
	} else return
	e.preventDefault()
}

function onwindowclick(e: MouseEvent) {
	if (!open) return
	const t = e.target as Node
	if (!menu?.contains(t) && !btn?.contains(t)) close()
}
</script>

<svelte:window onclick={onwindowclick} />

<span class={['spick', block && 'block']}>
	<button
		bind:this={btn}
		type="button"
		class={['spick-btn', value && 'on']}
		aria-haspopup="listbox"
		aria-expanded={open}
		aria-label="{label}: {current?.label ?? allLabel}"
		{disabled}
		onclick={() => (open ? close() : show())}
		onkeydown={(e) => {
			if (e.key === 'ArrowDown') {
				e.preventDefault()
				show()
			}
		}}
	>
		<Icon size={16} />
		<span class="spick-text">
			<span class="spick-kicker">{label}</span>
			<span class="spick-name">{current?.label ?? allLabel}</span>
		</span>
		<ChevronDown size={15} />
	</button>
	{#if open}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div bind:this={menu} class="spick-menu" onkeydown={onlistkey}>
			<label class="spick-search">
				<Search size={15} />
				<input
					bind:this={input}
					bind:value={query}
					aria-label="Search {noun}"
					placeholder="Search {fmt(options.length)} {noun}"
					type="search"
					onkeydown={oninputkey}
				/>
			</label>
			<div class="spick-list" role="listbox" aria-label={label}>
				{#if !query.trim()}
					<button type="button" role="option" aria-selected={value === ''} tabindex="-1" onclick={() => pick('')}>
						<span class="ck">{#if value === ''}<Check size={15} />{/if}</span>
						<span class="nm">{allLabel}</span>
						{#if allMeta}<span class="meta">{allMeta}</span>{/if}
					</button>
				{/if}
				{#each shown as o (o.id)}
					<button
						type="button"
						role="option"
						aria-selected={o.id === value}
						tabindex="-1"
						onclick={() => pick(o.id)}
					>
						<span class="ck">{#if o.id === value}<Check size={15} />{/if}</span>
						<span class="nm">{o.label}</span>
						{#if o.meta}<span class="meta">{o.meta}</span>{/if}
					</button>
				{:else}
					<p class="spick-note">No {noun} match “{query.trim()}”.</p>
				{/each}
			</div>
			{#if matches.length > SHOWN}
				<p class="spick-note foot">Showing {fmt(SHOWN)} of {fmt(matches.length)} · type to narrow down</p>
			{/if}
		</div>
	{/if}
</span>

<style>
	.spick {
		position: relative;
		display: inline-flex;
		min-width: 0;
	}
	.spick.block,
	.spick.block .spick-btn,
	.spick.block .spick-menu {
		display: flex;
		width: 100%;
	}
	.spick.block .spick-menu {
		display: block;
	}
	.spick-btn {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		width: 280px;
		max-width: 100%;
		height: 44px;
		padding: 0 10px 0 12px;
		border: 1px solid var(--sep-strong);
		border-radius: 10px;
		background: var(--card);
		color: var(--text);
		text-align: left;
	}
	.spick-btn:hover:not(:disabled) {
		background: var(--hover);
	}
	.spick-btn:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	.spick-btn[aria-expanded='true'] {
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--sel);
	}
	.spick-btn :global(svg) {
		flex: none;
		color: var(--text3);
	}
	.spick-btn.on {
		border-color: var(--accent);
	}
	.spick-btn.on :global(svg:first-child) {
		color: var(--accent);
	}
	.spick-text {
		display: grid;
		flex: 1;
		min-width: 0;
		line-height: 1.2;
	}
	.spick-kicker {
		font-size: 11px;
		color: var(--text3);
	}
	.spick-name {
		font-size: 14px;
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.spick-menu {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 30;
		width: min(400px, 90vw);
		background: var(--card);
		border: 1px solid var(--sep);
		border-radius: 12px;
		box-shadow: var(--shadow-lg);
		overflow: hidden;
	}
	.spick-search {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 0 12px;
		border-bottom: 1px solid var(--sep);
		color: var(--text3);
	}
	.spick-search input {
		flex: 1;
		height: 42px;
		border: 0;
		background: transparent;
		color: var(--text);
		font-size: 14px;
		outline: none;
	}
	.spick-list {
		max-height: min(360px, 55vh);
		overflow: auto;
		padding: 4px 0;
	}
	.spick-list button {
		display: flex;
		width: 100%;
		align-items: center;
		gap: 8px;
		padding: 8px 12px;
		text-align: left;
		color: var(--text);
		font-size: 13.5px;
	}
	.spick-list button:hover,
	.spick-list button:focus-visible {
		background: var(--hover);
		outline: none;
	}
	.spick-list button[aria-selected='true'] .nm {
		font-weight: 600;
	}
	.ck {
		width: 16px;
		flex: none;
		display: inline-grid;
		color: var(--accent);
	}
	.nm {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.meta {
		flex: none;
		color: var(--text3);
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	.spick-note {
		margin: 0;
		padding: 10px 12px;
		color: var(--text3);
		font-size: 12.5px;
	}
	.spick-note.foot {
		border-top: 1px solid var(--sep);
	}
</style>
