<script lang="ts">
	import { fly, fade } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';

	let {
		placeholder = 'Search properties, areas, or ask anything...',
		onSubmit = () => {},
		options = ['Custom deliverables', 'Valuation']
	}: {
		placeholder?: string;
		onSubmit?: (value: string) => void;
		options?: string[];
	} = $props();

	let inputValue = $state('');
	let showDropdown = $state(false);
	let dropdownOpenTimeout: number | undefined;
	let dropdownCloseTimeout: number | undefined;
	let textareaRef: HTMLTextAreaElement;

	function handleMouseEnterDropdown() {
		clearTimeout(dropdownCloseTimeout);
		clearTimeout(dropdownOpenTimeout);
		dropdownOpenTimeout = window.setTimeout(() => {
			showDropdown = true;
		}, 300);
	}

	function handleMouseLeaveDropdown() {
		clearTimeout(dropdownOpenTimeout);
		dropdownCloseTimeout = window.setTimeout(() => {
			showDropdown = false;
		}, 300);
	}

	function selectOption(option: string) {
		console.log('Selected:', option);
		showDropdown = false;
	}

	function autoResizeTextarea() {
		if (textareaRef) {
			textareaRef.style.height = 'auto';
			const newHeight = Math.min(textareaRef.scrollHeight, 200);
			textareaRef.style.height = newHeight + 'px';
		}
	}

	function handleSubmit() {
		if (inputValue.trim()) {
			onSubmit(inputValue);
			inputValue = '';
			if (textareaRef) textareaRef.style.height = 'auto';
		}
	}
</script>

<div class="w-full max-w-2xl">
	<div
		class="bg-white/80 backdrop-blur-xl rounded-2xl shadow-lg shadow-primary-pale/20 border border-primary-pale hover:shadow-xl hover:border-primary-pale/50 transition-all duration-300 overflow-visible px-5 py-4 flex flex-col"
	>
		<textarea
			bind:this={textareaRef}
			bind:value={inputValue}
			oninput={autoResizeTextarea}
			{placeholder}
			aria-label={placeholder}
			class="w-full bg-transparent outline-none text-gray-800 placeholder-gray-400 text-base font-medium resize-none min-h-[36px] max-h-[200px] leading-relaxed scrollbar-thin scrollbar-track-gray-100"
			rows="1"
		></textarea>
		<div class="flex items-center justify-between mt-0">
			<!-- Plus Dropdown -->
			<div
				class="relative dropdown-container -ml-2"
				onmouseenter={handleMouseEnterDropdown}
				onmouseleave={handleMouseLeaveDropdown}
				role="button"
				tabindex="0"
				aria-haspopup="menu"
				aria-expanded={showDropdown}
				aria-label="Open additional options"
			>
				<button
					type="button"
					class="p-2 rounded-lg text-gray-400 hover:text-primary hover:bg-primary-pale/30 transition-all duration-300"
					aria-label="Open additional options"
					title="Open additional options"
				>
					<svg
						class="w-5 h-5"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						viewBox="0 0 24 24"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
					</svg>
				</button>

				{#if showDropdown}
					<div
						class="absolute left-0 mt-3 w-48 bg-white rounded-lg shadow-xl py-2 border border-primary-pale z-50"
						onmouseenter={handleMouseEnterDropdown}
						onmouseleave={handleMouseLeaveDropdown}
						in:fly={{ y: -10, duration: 250, easing: quintOut }}
						out:fade={{ duration: 150 }}
						role="menu"
						tabindex="0"
						aria-label="Additional options"
					>
						{#each options as option (option)}
							<button
								type="button"
								role="menuitem"
								onclick={() => selectOption(option)}
								class="w-full text-left px-4 py-2.5 text-sm text-gray-700 hover:bg-primary-pale/40 hover:text-primary transition-colors duration-250"
							>
								{option}
							</button>
						{/each}
					</div>
				{/if}
			</div>
			<!-- Send Button -->
			<button
				type="button"
				aria-label="Send message"
				title="Send message"
				onclick={handleSubmit}
				disabled={!inputValue.trim()}
				class="flex-shrink-0 p-2 rounded-lg -mr-2 transition-all duration-200
          text-primary bg-primary-pale/40 hover:bg-primary-pale/60
          disabled:bg-primary-pale/20 disabled:text-gray-400 disabled:cursor-not-allowed"
			>
				<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
					<path
						d="M16.6915026,12.4744748 L3.50612381,13.2599618 C3.19218622,13.2599618 3.03521743,13.4170592 3.03521743,13.5741566 L1.15159189,20.0151496 C0.8376543,20.8006365 0.99,21.89 1.77946707,22.52 C2.41,22.99 3.50612381,23.1 4.13399899,22.8429026 L21.714504,14.0454487 C22.6563168,13.5741566 23.1272231,12.6315722 22.9702544,11.6889879 C22.9702544,11.6889879 22.9702544,11.5318905 22.9702544,11.4748031 L22.9702544,11.3177057 C22.9702544,10.3751214 22.6563168,9.43253706 21.714504,8.96126502 L4.13399899,0.163821323 C3.34915502,0.0567539539 2.40734225,0.163821323 1.77946707,0.637394323 C0.994623095,1.27108255 0.837654326,2.36036823 1.15159189,3.14585511 L3.03521743,9.58684815 C3.03521743,9.74394555 3.19218622,9.90104294 3.50612381,9.90104294 L16.6915026,10.6865299 C16.6915026,10.6865299 17.1624089,10.6865299 17.1624089,10.3751214 L17.1624089,12.6315722 C17.1624089,12.6315722 17.1624089,12.4744748 16.6915026,12.4744748 Z"
					/>
				</svg>
			</button>
		</div>
	</div>
</div>
