<svelte:head>
	<title>Payment Cancelled - Vitevue</title>
</svelte:head>

<div class="min-h-screen bg-gradient-to-br from-slate-50 to-white flex items-center justify-center p-4">
	<div class="w-full max-w-md">
		<div class="bg-white rounded-xl shadow-lg p-12 text-center">
			<div class="mb-6">
				<svg
					class="w-16 h-16 text-amber-500 mx-auto"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
					></path>
				</svg>
			</div>

			<h1 class="text-3xl font-bold text-slate-900 mb-3">Payment Cancelled</h1>

			<p class="text-slate-600 mb-8">
				Your payment was cancelled. No charges have been made to your account.
			</p>

			<div class="space-y-3">
				<a
					href="/organization-setup"
					class="block w-full bg-slate-900 hover:bg-slate-800 text-white font-semibold rounded-lg px-6 py-3 transition-colors"
				>
					Try Again
				</a>

				<a
					href="mailto:contact@vitevue.com"
					class="block w-full border border-slate-300 text-slate-700 font-semibold rounded-lg px-6 py-3 hover:bg-slate-50 transition-colors"
				>
					Contact Support
				</a>
			</div>

			<p class="text-sm text-slate-500 mt-8">
				Need help? Email us at
				<a href="mailto:contact@vitevue.com" class="text-slate-900 hover:underline">
					contact@vitevue.com
				</a>
			</p>
		</div>
	</div>
</div>
