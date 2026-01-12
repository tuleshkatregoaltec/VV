<script lang="ts">
	let isVisible = $state(false);

	$effect(() => {
		isVisible = true;
	});
</script>

<section id="preview" class="py-20 bg-gradient-to-b from-background to-background-surface overflow-hidden">
	<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
		<div class="text-center mb-20">
			<h2 class="text-4xl sm:text-5xl md:text-6xl font-bold text-gray-900 mb-4">
				AI that understands Dubai real estate
			</h2>
			<p class="text-xl text-gray-600 max-w-3xl mx-auto">
				Stop searching. Start asking.
			</p>
		</div>

		<!-- Feature 1: AI Chat - Full width with integrated visual -->
		<div class="mb-32 transition-all duration-700 {isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}">
			<div class="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
				<div class="order-2 lg:order-1">
					<div class="inline-block px-4 py-2 bg-[#009999]/10 rounded-full mb-4">
						<span class="text-[#009999] font-bold text-sm">AI-POWERED</span>
					</div>
					<h3 class="text-4xl md:text-5xl font-black text-gray-900 mb-6 leading-tight">
						Ask anything,<br />get instant answers
					</h3>
					<p class="text-xl text-gray-600 mb-8 leading-relaxed">
						"What's the average price per sqft in Dubai Marina for 2-bedroom units sold in the last 30 days?"
						Just ask. Our AI understands context, analyzes real-time data, and gives you the answer in seconds.
					</p>
					<ul class="space-y-4">
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-[#009999] flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-gray-700">Plain English queries, no technical jargon needed</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-[#009999] flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-gray-700">Analyzes millions of transactions in real-time</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-[#009999] flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-gray-700">Conversational follow-ups for deeper insights</span>
						</li>
					</ul>
				</div>
				<div class="order-1 lg:order-2 relative">
					<!-- Floating screenshot placeholder with depth -->
					<div class="relative">
						<div class="absolute -inset-4 bg-gradient-to-r from-[#009999]/20 to-blue-500/20 rounded-3xl blur-2xl"></div>
						<div class="relative bg-white rounded-2xl shadow-2xl border border-gray-200 p-6 transform hover:scale-105 transition-transform duration-300">
							<div class="flex items-center gap-2 mb-4 pb-3 border-b border-gray-200">
								<div class="w-3 h-3 rounded-full bg-red-400"></div>
								<div class="w-3 h-3 rounded-full bg-yellow-400"></div>
								<div class="w-3 h-3 rounded-full bg-green-400"></div>
							</div>
							<div class="space-y-3">
								<div class="bg-gray-50 rounded-lg p-4 text-sm text-gray-600">
									What's the average price per sqft in Dubai Marina?
								</div>
								<div class="bg-[#009999]/10 rounded-lg p-4 text-sm text-gray-700">
									Based on recent transactions, the average price per sqft in Dubai Marina is <strong>AED 2,340</strong> for residential units...
								</div>
							</div>
							<div class="mt-4 h-48 bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg flex items-center justify-center text-gray-400 text-sm">
								Chat Interface Screenshot
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Feature 2: Analytics - Reversed layout -->
		<div class="mb-32 transition-all duration-700 delay-200 {isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}">
			<div class="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
				<div class="relative">
					<div class="absolute -inset-4 bg-gradient-to-r from-purple-500/20 to-pink-500/20 rounded-3xl blur-2xl"></div>
					<div class="relative bg-white rounded-2xl shadow-2xl border border-gray-200 p-6 transform hover:scale-105 transition-transform duration-300">
						<div class="h-64 bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg flex items-center justify-center text-gray-400 text-sm mb-4">
							Dashboard Analytics Screenshot
						</div>
						<div class="grid grid-cols-3 gap-3">
							<div class="bg-green-50 rounded-lg p-3 border border-green-200">
								<div class="text-xs text-green-600 font-medium">Volume</div>
								<div class="text-lg font-bold text-green-900">1,234</div>
							</div>
							<div class="bg-blue-50 rounded-lg p-3 border border-blue-200">
								<div class="text-xs text-blue-600 font-medium">Avg Price</div>
								<div class="text-lg font-bold text-blue-900">2.3M</div>
							</div>
							<div class="bg-purple-50 rounded-lg p-3 border border-purple-200">
								<div class="text-xs text-purple-600 font-medium">Trend</div>
								<div class="text-lg font-bold text-purple-900">+12%</div>
							</div>
						</div>
					</div>
				</div>
				<div>
					<div class="inline-block px-4 py-2 bg-purple-500/10 rounded-full mb-4">
						<span class="text-purple-600 font-bold text-sm">REAL-LIVE DATA</span>
					</div>
					<h3 class="text-4xl md:text-5xl font-black text-gray-900 mb-6 leading-tight">
						Market intelligence<br />that never sleeps
					</h3>
					<p class="text-xl text-gray-600 mb-8 leading-relaxed">
						Every transaction, every trend, updated in real-time. See what's happening across Dubai's property market as it unfolds.
					</p>
					<ul class="space-y-4">
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-gray-700">Live transaction data from DLD</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-gray-700">Track 200+ active developments</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-gray-700">Spot trends before they become obvious</span>
						</li>
					</ul>
				</div>
			</div>
		</div>

		<!-- Feature 3: Filtering - Full width again -->
		<div class="transition-all duration-700 delay-300 {isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}">
			<div class="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
				<div class="order-2 lg:order-1">
					<div class="inline-block px-4 py-2 bg-orange-500/10 rounded-full mb-4">
						<span class="text-orange-600 font-bold text-sm">SMART SEARCH</span>
					</div>
					<h3 class="text-4xl md:text-5xl font-black text-gray-900 mb-6 leading-tight">
						Find exactly what<br />you're looking for
					</h3>
					<p class="text-xl text-gray-600 mb-8 leading-relaxed">
						Advanced filtering that actually makes sense. Slice and dice data by area, property type, price range, bedrooms, and more—all in real-time.
					</p>
					<ul class="space-y-4">
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-orange-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-gray-700">Multi-dimensional filtering in 3 clicks</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-orange-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-gray-700">Export filtered results to Excel instantly</span>
						</li>
						<li class="flex items-start gap-3">
							<div class="w-6 h-6 rounded-full bg-orange-600 flex items-center justify-center flex-shrink-0 mt-1">
								<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
								</svg>
							</div>
							<span class="text-lg text-gray-700">Save custom filter combinations</span>
						</li>
					</ul>
				</div>
				<div class="order-1 lg:order-2 relative">
					<div class="absolute -inset-4 bg-gradient-to-r from-orange-500/20 to-yellow-500/20 rounded-3xl blur-2xl"></div>
					<div class="relative bg-white rounded-2xl shadow-2xl border border-gray-200 p-6 transform hover:scale-105 transition-transform duration-300">
						<div class="h-80 bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg flex items-center justify-center text-gray-400 text-sm">
							Transactions Table Screenshot
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</section>
