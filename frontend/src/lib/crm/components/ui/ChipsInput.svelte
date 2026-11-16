<script lang="ts">
import X from 'lucide-svelte/icons/x'

/**
 * A list of values as removable chips with a box to add more (Enter or comma). `options` open
 * as a list under the box (click, or arrow keys and Enter); with `strict`, only they can be
 * added. Long lists show the first few and "+N", which opens the rest.
 */
let {
	values = $bindable([]),
	options = [],
	strict = false,
	placeholder = 'Type and press Enter',
	label,
	collapseAfter = 3
}: {
	values?: string[]
	options?: { value: string; label: string }[]
	strict?: boolean
	placeholder?: string
	label: string
	collapseAfter?: number
} = $props()

const uid = $props.id()
let text = $state('')
let expanded = $state(false)
let open = $state(false)
let active = $state(0)

const labelOf = (v: string) => options.find((o) => o.value === v)?.label ?? v
/** Options not chosen yet that contain what is typed. */
const left = $derived(
	options.filter(
		(o) =>
			!values.some((v) => v.toLowerCase() === o.value.toLowerCase()) &&
			o.label.toLowerCase().includes(text.trim().toLowerCase())
	)
)
const shown = $derived(expanded ? values : values.slice(0, collapseAfter))
const listOpen = $derived(open && left.length > 0)

function add(raw: string) {
	for (const part of raw.split(',')) {
		const typed = part.trim()
		if (!typed) continue
		const match = options.find(
			(o) =>
				o.value.toLowerCase() === typed.toLowerCase() ||
				o.label.toLowerCase() === typed.toLowerCase()
		)
		if (strict && !match) continue
		const value = match?.value ?? typed
		if (!values.some((v) => v.toLowerCase() === value.toLowerCase())) values = [...values, value]
	}
	text = ''
	active = 0
}

function onkeydown(e: KeyboardEvent) {
	if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
		e.preventDefault()
		open = true
		if (left.length)
			active = (active + (e.key === 'ArrowDown' ? 1 : -1) + left.length) % left.length
	} else if (e.key === 'Enter' || e.key === ',') {
		e.preventDefault()
		// A highlighted suggestion wins over half-typed text (Enter only: a comma separates values).
		if (e.key === 'Enter' && listOpen && left[active]) add(left[active].value)
		else add(text)
	} else if (e.key === 'Escape') {
		open = false
	} else if (e.key === 'Backspace' && !text && values.length) {
		values = values.slice(0, -1)
	}
}
</script>

<div class="wrap">
	<div class="chips">
		{#each shown as v (v)}
			<span class="chip">
				{labelOf(v)}
				<button type="button" aria-label="Remove {labelOf(v)} from {label}" onclick={() => (values = values.filter((x) => x !== v))}>
					<X size={12} />
				</button>
			</span>
		{/each}
		{#if values.length > shown.length}
			<button type="button" class="chip more" onclick={() => (expanded = true)}>+{values.length - shown.length}</button>
		{/if}
		<input
			aria-label={label}
			role={options.length ? 'combobox' : undefined}
			aria-expanded={options.length ? listOpen : undefined}
			aria-controls={options.length ? `${uid}-list` : undefined}
			aria-activedescendant={listOpen ? `${uid}-opt-${active}` : undefined}
			autocomplete="off"
			bind:value={text}
			{onkeydown}
			oninput={() => ((open = true), (active = 0))}
			onfocus={() => (open = true)}
			onblur={() => {
				open = false
				if (text) add(text)
			}}
			placeholder={values.length ? (options.length && left.length ? 'Add more…' : '') : placeholder}
		/>
	</div>
	{#if listOpen}
		<ul class="suggest" id="{uid}-list" role="listbox" aria-label="{label} suggestions">
			{#each left as o, i (o.value)}
				<li
					id="{uid}-opt-{i}"
					role="option"
					aria-selected={i === active}
					class={[i === active && 'active']}
					onmousedown={(e) => {
						// Keep the box focused, so the list stays open for the next pick.
						e.preventDefault()
						add(o.value)
					}}
					onmouseenter={() => (active = i)}
				>
					{o.label}
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.wrap {
		position: relative;
	}
	.suggest {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		right: 0;
		z-index: 20;
		max-height: 240px;
		overflow-y: auto;
		margin: 0;
		padding: 4px;
		list-style: none;
		border: 1px solid var(--sep);
		border-radius: 8px;
		background: var(--card);
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.3);
	}
	.suggest li {
		padding: 7px 10px;
		border-radius: 6px;
		font-size: 14px;
		color: var(--text);
		cursor: pointer;
	}
	.suggest li.active {
		background: var(--sunk);
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.3rem;
		min-height: 36px;
		padding: 0.25rem 0.4rem;
		border: 1px solid var(--sep);
		border-radius: 8px;
		background: var(--card);
	}
	.chips:focus-within {
		border-color: var(--accent);
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.2rem;
		padding: 0.1rem 0.25rem 0.1rem 0.5rem;
		border: 1px solid var(--sep);
		border-radius: 6px;
		background: var(--sunk);
		font-size: 13px;
		color: var(--text);
	}
	.chip button {
		display: grid;
		place-items: center;
		padding: 0.1rem;
		border: 0;
		background: none;
		color: var(--text2);
		cursor: pointer;
	}
	.chip.more {
		padding: 0.1rem 0.5rem;
		cursor: pointer;
	}
	input {
		flex: 1;
		min-width: 8rem;
		border: 0;
		background: none;
		padding: 0.2rem;
		outline: none;
	}
</style>
