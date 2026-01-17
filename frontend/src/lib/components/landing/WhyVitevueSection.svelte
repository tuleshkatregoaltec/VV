<script lang="ts">
	const features = [
		{ text: 'Verified DLD transaction data' },
		{ text: '200+ tracked projects and developments' },
		{ text: 'Real-time rental and sales analytics' },
		{ text: 'AI-powered market insights' },
		{ text: 'Export-ready reports and analysis' },
		{ text: 'Enterprise-grade security' }
	];
</script>

<section class="py-24 bg-white relative overflow-hidden">
	<!-- Floating decorative element -->
	<div class="absolute top-1/4 right-10 w-32 h-32 bg-teal-100 rounded-full blur-3xl opacity-30 animate-float-slow"></div>
	<div class="absolute bottom-1/4 left-10 w-40 h-40 bg-cyan-100 rounded-full blur-3xl opacity-30 animate-float-delayed"></div>

	<div class="max-w-6xl mx-auto px-6 lg:px-8">
		<div class="max-w-5xl mx-auto">
			<div class="text-center mb-16">
				<div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-200 rounded-full mb-6 hover:scale-105 hover:shadow-md transition-all duration-300">
					<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
					</svg>
					<span class="text-sm font-semibold text-slate-700">What's Included</span>
				</div>
				<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-6 leading-tight hover:scale-[1.02] transition-transform duration-500">
					Complete market intelligence in
					<span class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent">
						one platform
					</span>
				</h2>
				<p class="text-xl text-slate-600">
					Everything you need to analyze the Dubai real estate market
				</p>
			</div>

			<div class="bg-slate-50 rounded-2xl p-8 sm:p-12 border border-slate-200">
				<div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-12">
					{#each features as feature}
						<div class="flex items-start gap-3">
							<div class="flex-shrink-0 w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center mt-0.5">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<p class="text-slate-700 font-medium">
								{feature.text}
							</p>
						</div>
					{/each}
				</div>

				<div class="pt-8 border-t border-slate-200">
					<div class="grid grid-cols-1 sm:grid-cols-3 gap-6">
						<div class="text-center p-6 bg-white rounded-xl border border-slate-200">
							<div class="text-3xl font-bold text-slate-900 mb-2">
								10,000+
							</div>
							<div class="text-sm text-slate-600">Daily transactions analyzed</div>
						</div>
						<div class="text-center p-6 bg-white rounded-xl border border-slate-200">
							<div class="text-3xl font-bold text-slate-900 mb-2">
								200+
							</div>
							<div class="text-sm text-slate-600">Active projects tracked</div>
						</div>
						<div class="text-center p-6 bg-white rounded-xl border border-slate-200">
							<div class="text-3xl font-bold text-slate-900 mb-2">
								24/7
							</div>
							<div class="text-sm text-slate-600">Real-time updates</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</section>
