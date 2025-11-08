<script lang="ts">
	import { fly, fade } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';

	import { onMount } from 'svelte';
	export let label = 'Filter';
	export let options: string[] = [];
	export let selected = options[0];
	let rootEl: HTMLDivElement;
	let open = false;

	// For animating width and delayed text update
	let buttonEl: HTMLButtonElement;
	let measureEl: HTMLSpanElement;
	let buttonWidth = 0;
	let visibleSelected = selected;

	function getWidth(val: string | undefined): number {
		if (!measureEl || val == null) return 0;
		// Use a span to measure width without direct DOM mutation
		measureEl.innerText = val;
		return measureEl.offsetWidth + 40;
	}
	function updateButtonWidth(val: string | undefined = visibleSelected) {
		buttonWidth = getWidth(val);
	}

	function toggleDropdown() {
		open = !open;
	}

	function selectOption(option: string) {
		if (option === visibleSelected) return (open = false);
		const newWidth = getWidth(option);
		const shrinking = newWidth < buttonWidth;
		if (shrinking) {
			// Shrinking: update text first, then animate
			visibleSelected = option;
			updateButtonWidth(option);
			setTimeout(() => {
				open = false;
				updateButtonWidth();
			}, 80);
		} else {
			// Expanding: animate width first, then update text
			updateButtonWidth(option);
			setTimeout(() => {
				visibleSelected = option;
				updateButtonWidth(option);
				open = false;
				updateButtonWidth();
			}, 80);
		}
	}

	// Update width on mount and when visibleSelected changes
	$: if (visibleSelected) updateButtonWidth();
	// Keep exported selected in sync with visibleSelected
	$: if (selected !== visibleSelected) selected = visibleSelected;

	function handleDocumentClick(e: MouseEvent) {
		if (open && rootEl && !rootEl.contains(e.target as Node)) {
			open = false;
		}
	}

	onMount(() => {
		setTimeout(updateButtonWidth, 0);
		document.addEventListener('mousedown', handleDocumentClick);
		return () => {
			document.removeEventListener('mousedown', handleDocumentClick);
		};
	});
</script>

<div class="relative w-fit" bind:this={rootEl}>
	<button
		class="pl-4 pr-0 py-2 rounded-lg bg-white/80 backdrop-blur-xl border border-primary-pale text-gray-700 font-medium hover:border-primary-pale/70 hover:shadow-lg transition-all duration-300 flex items-center whitespace-nowrap"
		aria-haspopup="listbox"
		aria-expanded={open}
		aria-controls="{label}-dropdown-list"
		on:click={toggleDropdown}
		type="button"
		bind:this={buttonEl}
		style="width: {buttonWidth
			? buttonWidth
			: 'auto'}px; transition: width 80ms cubic-bezier(0.4,0,0.2,1); overflow: hidden;"
	>
		<span class="flex items-center gap-2">
			{visibleSelected}
			<svg class="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
			</svg>
		</span>
		<span
			class="absolute left-0 top-0 opacity-0 pointer-events-none whitespace-pre whitespace-nowrap flex items-center gap-2"
			bind:this={measureEl}
			style="position: absolute; visibility: hidden; padding-left: 1rem; padding-right: 0;"
		>
			{visibleSelected}
			<svg class="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"
				><path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M19 9l-7 7-7-7"
				/></svg
			>
		</span>
	</button>

	{#if open}
		<div
			id="{label}-dropdown-list"
			class="absolute mt-2 w-48 bg-white rounded-lg shadow-xl py-2 z-50 {label === 'Timeframe'
				? 'right-0'
				: 'left-0'}"
			role="listbox"
			in:fly={{ y: -10, duration: 400, easing: quintOut }}
			out:fade={{ duration: 200 }}
		>
			{#each options as option (option)}
				<button
					on:click={() => selectOption(option)}
					class="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-primary-pale/40 hover:text-primary transition-colors duration-250 {selected ===
					option
						? 'bg-primary-pale/20 text-primary font-semibold'
						: ''}"
					role="option"
					aria-selected={selected === option}
				>
					{option}
				</button>
			{/each}
		</div>
	{/if}
</div>
