<script lang="ts">
	import { onMount } from 'svelte';

	let isVisible = $state(false);
	let featuresInView = $state<boolean[]>([false, false, false]);
	let sectionElement: HTMLElement;

	$effect(() => {
		isVisible = true;
	});

	onMount(() => {
		const observer = new IntersectionObserver(
			(entries) => {
				entries.forEach((entry) => {
					if (entry.isIntersecting) {
						const featureIndex = parseInt(entry.target.getAttribute('data-feature-index') || '0');
						featuresInView[featureIndex] = true;
					}
				});
			},
			{ threshold: 0.2 }
		);

		const features = sectionElement.querySelectorAll('[data-feature-index]');
		features.forEach((feature) => observer.observe(feature));

		return () => observer.disconnect();
	});
</script>

<section bind:this={sectionElement} id="preview" class="py-24 bg-white relative overflow-hidden">
	<!-- Floating decorative elements -->
	<div class="absolute top-1/3 right-20 w-40 h-40 bg-teal-100 rounded-full blur-3xl opacity-20 animate-float-slow"></div>
	<div class="absolute bottom-1/3 left-20 w-48 h-48 bg-cyan-100 rounded-full blur-3xl opacity-20 animate-float-delayed"></div>

	<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative">
		<div class="text-center mb-20">
			<!-- Section badge -->
			<div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-200 rounded-full mb-6 shadow-sm hover:scale-105 transition-all duration-300">
				<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path>
				</svg>
				<span class="text-sm font-semibold text-slate-700">Platform Overview</span>
			</div>

			<h2 class="text-4xl sm:text-5xl md:text-6xl font-bold text-slate-900 mb-4 hover:scale-[1.02] transition-transform duration-500">
				AI that understands
				<span class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent">
					Dubai real estate
				</span>
			</h2>
			<p class="text-xl text-slate-600 max-w-3xl mx-auto">
				Stop searching. Start asking.
			</p>
		</div>

		<!-- Feature 1: AI Chat - Full width with integrated visual -->
		<div
			data-feature-index="0"
			class="mb-32 transition-all duration-700"
			style="transform: scale({featuresInView[0] ? 1 : 0.95}); opacity: {featuresInView[0] ? 1 : 0}"
		>
			<div class="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
				<div class="order-2 lg:order-1">
					<div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-200 rounded-full mb-6 shadow-sm">
						<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path>
						</svg>
						<span class="text-sm font-semibold text-slate-700">AI-POWERED</span>
					</div>
					<h3 class="text-4xl md:text-5xl font-bold text-slate-900 mb-6 leading-tight">
						Ask anything,<br />
						<span class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent">
							get instant answers
						</span>
					</h3>
					<p class="text-xl text-slate-600 mb-8 leading-relaxed">
						"What's the average price per sqft in Dubai Marina for 2-bedroom units sold in the last 30 days?"
						Just ask. Our AI understands context, analyzes data in real-time, and gives you the answer in seconds.
					</p>
					<ul class="space-y-4">
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-slate-700 font-medium">No time wasted manually finding and analyzing data</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-slate-700 font-medium">Accesses millions of transactions in real-time</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-slate-700 font-medium">Conversational follow-ups for deeper insights</span>
						</li>
					</ul>
				</div>
				<div class="order-1 lg:order-2 relative">
					<!-- Floating screenshot placeholder with depth -->
					<div class="relative group">
						<div class="absolute -inset-4 bg-gradient-to-r from-teal-500/20 to-cyan-500/20 rounded-3xl blur-2xl group-hover:blur-3xl transition-all"></div>
					<div class="relative bg-white rounded-2xl shadow-2xl border border-slate-200 p-3 transform hover:scale-105 hover:-translate-y-2 transition-all duration-300">
							<img src="/chat.png" alt="Chat Interface" class="w-full h-auto rounded-lg border border-slate-200" />
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Feature 2: Analytics - Reversed layout -->
		<div
			data-feature-index="1"
			class="mb-32 transition-all duration-700 delay-200"
			style="transform: scale({featuresInView[1] ? 1 : 0.95}); opacity: {featuresInView[1] ? 1 : 0}"
		>
			<div class="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
				<div class="relative group">
					<div class="absolute -inset-4 bg-gradient-to-r from-teal-500/20 to-cyan-500/20 rounded-3xl blur-2xl group-hover:blur-3xl transition-all"></div>
					<div class="relative bg-white rounded-2xl shadow-2xl border border-slate-200 p-6 transform hover:scale-105 hover:-translate-y-2 transition-all duration-300">
						<div class="h-64 bg-gradient-to-br from-slate-50 to-slate-100 rounded-lg flex items-center justify-center text-slate-400 text-sm mb-4 border border-slate-200">
							Dashboard Analytics Screenshot
						</div>
						<div class="grid grid-cols-3 gap-3">
							<div class="bg-teal-50 rounded-lg p-3 border border-teal-200">
								<div class="text-xs text-teal-700 font-semibold">Volume</div>
								<div class="text-lg font-bold text-slate-900">1,234</div>
							</div>
							<div class="bg-cyan-50 rounded-lg p-3 border border-cyan-200">
								<div class="text-xs text-cyan-700 font-semibold">Avg Price</div>
								<div class="text-lg font-bold text-slate-900">2.3M</div>
							</div>
							<div class="bg-slate-50 rounded-lg p-3 border border-slate-200">
								<div class="text-xs text-slate-700 font-semibold">Trend</div>
								<div class="text-lg font-bold text-teal-700">+12%</div>
							</div>
						</div>
					</div>
				</div>
				<div>
					<div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-200 rounded-full mb-6 shadow-sm">
						<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
						</svg>
						<span class="text-sm font-semibold text-slate-700">REAL-TIME DATA</span>
					</div>
					<h3 class="text-4xl md:text-5xl font-bold text-slate-900 mb-6 leading-tight">
						Market intelligence<br />
						<span class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent">
							that never sleeps
						</span>
					</h3>
					<p class="text-xl text-slate-600 mb-8 leading-relaxed">
						Every transaction, every trend. See what's happening across Dubai's property market as it unfolds.
					</p>
					<ul class="space-y-4">
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-slate-700 font-medium">Live transaction data from DLD</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-slate-700 font-medium">Track 200+ active developments</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-slate-700 font-medium">Spot trends before they become obvious</span>
						</li>
					</ul>
				</div>
			</div>
		</div>

		<!-- Feature 3: Filtering - Full width again -->
		<div
			data-feature-index="2"
			class="transition-all duration-700 delay-300"
			style="transform: scale({featuresInView[2] ? 1 : 0.95}); opacity: {featuresInView[2] ? 1 : 0}"
		>
			<div class="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
				<div class="order-2 lg:order-1">
					<div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-50 border border-slate-200 rounded-full mb-6 shadow-sm">
						<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"></path>
						</svg>
						<span class="text-sm font-semibold text-slate-700">SMART SEARCH</span>
					</div>
					<h3 class="text-4xl md:text-5xl font-bold text-slate-900 mb-6 leading-tight">
						Find exactly what<br />
						<span class="bg-gradient-to-r from-teal-600 to-cyan-600 bg-clip-text text-transparent">
							you're looking for
						</span>
					</h3>
					<p class="text-xl text-slate-600 mb-8 leading-relaxed">
						Advanced filtering that actually makes sense. Slice and dice data by area, property type, price range, bedrooms, and more.
					</p>
					<ul class="space-y-4">
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-slate-700 font-medium">Multi-dimensional filtering in an instant</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-slate-700 font-medium">Export filtered results directly to Excel</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-teal-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-slate-700 font-medium">Quickly browse both rental and sales data</span>
						</li>
					</ul>
				</div>
				<div class="order-1 lg:order-2 relative">
					<div class="relative group">
						<div class="absolute -inset-4 bg-gradient-to-r from-teal-500/20 to-cyan-500/20 rounded-3xl blur-2xl group-hover:blur-3xl transition-all"></div>
					<div class="relative bg-white rounded-2xl shadow-2xl border border-slate-200 p-3 transform hover:scale-105 hover:-translate-y-2 transition-all duration-300">
						<img src="/transactions.png" alt="Transactions Table" class="w-full h-auto rounded-lg border border-slate-200" />
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</section>
