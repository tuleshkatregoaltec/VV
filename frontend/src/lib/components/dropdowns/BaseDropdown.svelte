<script module lang="ts">
let nextId = 0
</script>

<script lang="ts">
	import { getContext } from 'svelte';
	import { fly, fade } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import type { Snippet } from 'svelte';

	let {
		id = `dropdown-${nextId++}`,
		ariaLabel,
		displayValue,
		align = 'left',
		button,
		children,
		onOpen,
		onClose
	}: {
		id?: string;
		ariaLabel: string;
		displayValue: string;
		align?: 'left' | 'right';
		button?: Snippet<[{ toggle: () => void; isOpen: boolean }]>;
		children: Snippet<[{ close: () => void }]>;
		onOpen?: () => void;
		onClose?: () => void;
	} = $props();

	let localState = $state<string | null>(null);
	let openDropdownIdContext = getContext<{ value: string | null }>('openDropdownId') ?? {
		get value() {
			return localState;
		},
		set value(v: string | null) {
			localState = v;
		}
	};

	let isOpen = $derived(openDropdownIdContext.value === id);

	let wasOpen = $state(false);

	$effect(() => {
		if (isOpen && !wasOpen) {
			onOpen?.();
			wasOpen = true;
		} else if (!isOpen && wasOpen) {
			onClose?.();
			wasOpen = false;
		}
	});

	function toggle() {
		openDropdownIdContext.value = isOpen ? null : id;
	}

	function close() {
		openDropdownIdContext.value = null;
	}

	// Reusable click outside action
	function clickOutside(node: HTMLElement, callback: () => void) {
		function handleClick(event: MouseEvent) {
			if (!node.contains(event.target as Node)) {
				callback();
			}
		}

		document.addEventListener('mousedown', handleClick, true);

		return {
			destroy() {
				document.removeEventListener('mousedown', handleClick, true);
			}
		};
	}
</script>

<div
	id="dropdown-container-{id}"
	use:clickOutside={() => {
		if (isOpen) close();
	}}
>
	<div class="relative">
		{#if button}
			{@render button({ toggle, isOpen })}
		{:else}
			<button
				id="{id}-button"
				type="button"
				class="flex w-full items-center justify-between rounded-md border border-[var(--color-border)] bg-white px-3 py-2 text-left text-sm text-[var(--color-fg-1)] transition-all duration-150 hover:border-[var(--color-border-strong)] hover:bg-slate-50 focus:border-[var(--color-navy-900)] focus:outline-none focus:ring-2 focus:ring-[rgba(11,27,43,0.12)]"
				onclick={toggle}
				aria-label={ariaLabel}
				aria-haspopup="true"
				aria-expanded={isOpen}
			>
				<span class={!displayValue ? 'text-[var(--color-fg-5)]' : ''}>
					{displayValue || 'Select...'}
				</span>
				<svg
					class="h-4 w-4 text-[var(--color-fg-4)] transition-transform duration-200"
					class:rotate-180={isOpen}
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					viewBox="0 0 24 24"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
				</svg>
			</button>
		{/if}

		{#if isOpen}
			<div
				class="absolute z-50 mt-2 overflow-hidden rounded-lg border border-[var(--color-border)] bg-white shadow-lg {align ===
				'right'
					? 'right-0'
					: 'left-0'}"
				style={align === 'right' ? 'min-width: 200px;' : 'width: 100%;'}
				in:fly={{ y: -10, duration: 200, easing: quintOut }}
				out:fade={{ duration: 150 }}
			>
				{@render children({ close })}
			</div>
		{/if}
	</div>
</div>
