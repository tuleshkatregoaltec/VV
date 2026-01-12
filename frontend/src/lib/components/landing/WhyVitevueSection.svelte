<script lang="ts">
	const features = [
		{ text: 'Verified DLD transaction data', icon: '✓' },
		{ text: '200+ tracked projects and developments', icon: '✓' },
		{ text: 'Real-time rental and sales analytics', icon: '✓' },
		{ text: 'AI-powered market insights', icon: '✓' },
		{ text: 'Export-ready reports and analysis', icon: '✓' },
		{ text: 'Enterprise-grade security', icon: '✓' }
	];
</script>

<section class="py-24 bg-gradient-to-b from-background to-background-surface relative overflow-hidden">
	<!-- Decorative background -->
	<div class="absolute top-1/4 right-0 w-96 h-96 bg-gradient-to-br from-[#009999]/10 to-transparent rounded-full blur-3xl"></div>

	<div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
		<div class="max-w-5xl mx-auto">
			<div class="text-center mb-16">
				<div class="inline-block px-4 py-2 bg-green-500/10 rounded-full mb-6">
					<span class="text-green-600 font-bold text-sm tracking-wide">THE DIFFERENCE</span>
				</div>
				<h2 class="text-4xl sm:text-5xl md:text-6xl font-black text-gray-900 mb-6 leading-tight">
					Why Dubai professionals<br />
					<span class="bg-gradient-to-r from-green-600 to-teal-600 bg-clip-text text-transparent">
						choose Vitevue
					</span>
				</h2>
				<p class="text-xl sm:text-2xl text-gray-600">
					The most comprehensive real estate intelligence platform in Dubai
				</p>
			</div>

			<div class="bg-gradient-to-br from-white to-gray-50 rounded-3xl p-8 sm:p-12 shadow-2xl border-2 border-gray-200">
				<div class="grid grid-cols-1 md:grid-cols-2 gap-8 mb-12">
					{#each features as feature, i}
						<div class="flex items-start gap-4 group" style="animation-delay: {i * 50}ms;">
							<div class="flex-shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-[#009999] to-[#007777] text-white flex items-center justify-center font-bold group-hover:scale-110 group-hover:rotate-6 transition-all duration-300 shadow-lg">
								{feature.icon}
							</div>
							<p class="text-lg text-gray-800 font-semibold pt-2 group-hover:text-[#009999] transition-colors duration-300">
								{feature.text}
							</p>
						</div>
					{/each}
				</div>

				<div class="pt-8 border-t-2 border-gray-200">
					<p class="text-center text-gray-600 text-lg mb-8 font-medium">
						Join hundreds of professionals making smarter decisions every day
					</p>
					<div class="grid grid-cols-1 sm:grid-cols-3 gap-6">
						<div class="text-center p-6 bg-white rounded-2xl shadow-md hover:shadow-lg transition-shadow duration-300 border border-gray-100">
							<div class="text-4xl sm:text-5xl font-black bg-gradient-to-r from-[#009999] to-blue-600 bg-clip-text text-transparent mb-2">
								10,000+
							</div>
							<div class="text-sm text-gray-600 font-semibold">Transactions analyzed daily</div>
						</div>
						<div class="text-center p-6 bg-white rounded-2xl shadow-md hover:shadow-lg transition-shadow duration-300 border border-gray-100">
							<div class="text-4xl sm:text-5xl font-black bg-gradient-to-r from-purple-600 to-pink-600 bg-clip-text text-transparent mb-2">
								200+
							</div>
							<div class="text-sm text-gray-600 font-semibold">Active projects tracked</div>
						</div>
						<div class="text-center p-6 bg-white rounded-2xl shadow-md hover:shadow-lg transition-shadow duration-300 border border-gray-100">
							<div class="text-4xl sm:text-5xl font-black bg-gradient-to-r from-green-600 to-teal-600 bg-clip-text text-transparent mb-2">
								24/7
							</div>
							<div class="text-sm text-gray-600 font-semibold">Real-time updates</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</section>
