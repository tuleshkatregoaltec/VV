<script lang="ts">
	import { fade, scale } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';

	export let initialEmail = '';
	export let onClose: () => void;

	let email = initialEmail;
	let name = '';
	let company = '';
	let phone = '';
	let submitted = false;
	let emailInput: HTMLInputElement;

	function handleSubmit() {
		submitted = true;
		// Reset form
		setTimeout(() => {
			email = '';
			name = '';
			company = '';
			phone = '';
		}, 2000);
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) {
			onClose();
		}
	}

	// Autofocus email input when modal opens
	$: if (emailInput) {
		emailInput.focus();
	}
</script>

<!-- Backdrop as div with keyboard a11y -->
<div
	class="fixed inset-0 bg-black/40 backdrop-blur-sm z-[100] flex items-center justify-center p-4"
	on:click={handleBackdropClick}
	on:keydown={(e) => {
		if (e.key === 'Escape') onClose();
	}}
	transition:fade={{ duration: 300 }}
	role="dialog"
	aria-modal="true"
	aria-labelledby="modal-title"
	aria-label="Close modal by clicking or pressing Escape/Enter"
	tabindex="0"
>
	<!-- Modal -->
	<section
		class="bg-white rounded-2xl shadow-2xl max-w-md w-full p-8 relative"
		transition:scale={{ duration: 400, easing: quintOut, start: 0.9, opacity: 0 }}
		role="document"
		aria-describedby="modal-desc"
		aria-labelledby="modal-title"
	>
		<!-- Close button -->
		<button
			on:click={onClose}
			class="absolute top-4 right-4 text-gray-400 hover:text-gray-600 transition-colors"
			aria-label="Close modal"
		>
			<svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M6 18L18 6M6 6l12 12"
				/>
			</svg>
		</button>

		{#if submitted}
			<div class="text-center py-8">
				<div class="text-6xl mb-4">✓</div>
				<h3 class="text-2xl font-bold text-gray-900 mb-2">You're on the list!</h3>
				<p class="text-gray-600 mb-6">Thanks for joining. We'll be in touch soon with updates.</p>
			</div>
		{:else}
			<form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4" autocomplete="off">
				<h2 id="modal-title" class="text-2xl font-bold text-gray-900 mb-2">Join the waitlist</h2>
				<p id="modal-desc" class="text-gray-600 mb-2">
					Get early access to the future of real-estate market insights.
				</p>

				<div>
					<label for="modal-email" class="block text-sm font-semibold text-gray-800 mb-1">
						Email
					</label>
					<input
						id="modal-email"
						type="email"
						bind:value={email}
						bind:this={emailInput}
						placeholder="you@company.com"
						required
						class="w-full px-3 py-2 rounded border border-gray-200 text-gray-900 placeholder-gray-400 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all"
						aria-required="true"
						aria-label="Email"
					/>
				</div>

				<div>
					<label for="modal-name" class="block text-sm font-semibold text-gray-800 mb-1">
						Full Name
					</label>
					<input
						id="modal-name"
						type="text"
						bind:value={name}
						placeholder="John Doe"
						required
						class="w-full px-3 py-2 rounded border border-gray-200 text-gray-900 placeholder-gray-400 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all"
						aria-required="true"
						aria-label="Full Name"
					/>
				</div>

				<div>
					<label for="modal-company" class="block text-sm font-semibold text-gray-800 mb-1">
						Company
					</label>
					<input
						id="modal-company"
						type="text"
						bind:value={company}
						placeholder="Your Company"
						required
						class="w-full px-3 py-2 rounded border border-gray-200 text-gray-900 placeholder-gray-400 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all"
						aria-required="true"
						aria-label="Company"
					/>
				</div>

				<div>
					<label for="modal-phone" class="block text-sm font-semibold text-gray-800 mb-1">
						Phone Number
					</label>
					<input
						id="modal-phone"
						type="tel"
						bind:value={phone}
						placeholder="+971 50 123 4567"
						required
						class="w-full px-3 py-2 rounded border border-gray-200 text-gray-900 placeholder-gray-400 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all"
						aria-required="true"
						aria-label="Phone Number"
					/>
				</div>

				<button
					type="submit"
					disabled={!email || !name || !company || !phone}
					class="w-full px-4 py-3 rounded-lg bg-primary text-white font-semibold shadow hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 mt-2"
				>
					Join Waitlist
				</button>
			</form>
		{/if}
	</section>
</div>
