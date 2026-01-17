<script lang="ts">
	import { fly, fade } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';

	let isVisible = $state(false);

	$effect(() => {
		isVisible = true;
	});

	const features = [
		{
			title: 'Talk to your data',
			description: '"Which areas saw the highest price growth last quarter?" Ask in plain English. Get answers backed by real transaction data—instantly.',
			icon: 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
			color: 'from-teal-500 to-cyan-600',
			iconBg: 'bg-gradient-to-br from-teal-50 to-cyan-50',
			iconColor: 'text-teal-600'
		},
		{
			title: 'Every transaction, tracked',
			description: 'Over 50,000 sales and rentals across 200+ projects. See what sold, for how much, and when—with filters that actually work.',
			icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
			color: 'from-blue-500 to-indigo-600',
			iconBg: 'bg-gradient-to-br from-blue-50 to-indigo-50',
			iconColor: 'text-blue-600'
		},
		{
			title: "Know what's coming",
			description: 'Track new launches, delivery schedules, and unit availability. Spot oversupply risks before they become problems.',
			icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4',
			color: 'from-purple-500 to-pink-600',
			iconBg: 'bg-gradient-to-br from-purple-50 to-pink-50',
			iconColor: 'text-purple-600'
		},
		{
			title: 'Reports that close deals',
			description: 'Generate professional market analyses in minutes, not hours. Show up to every client meeting with data they can trust.',
			icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
			color: 'from-orange-500 to-red-600',
			iconBg: 'bg-gradient-to-br from-orange-50 to-red-50',
			iconColor: 'text-orange-600'
		}
	];

	const useCases = [
		{
			role: 'Brokers & Agents',
			icon: 'M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z',
			problem: 'Hours spent pulling comps from spreadsheets',
			solution: 'Live comparable data at your fingertips—price any unit with confidence in seconds'
		},
		{
			role: 'Investors',
			icon: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6',
			problem: 'Missing opportunities in a fast-moving market',
			solution: 'Spot emerging trends and undervalued areas before your competition does'
		},
		{
			role: 'Consultants',
			icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
			problem: 'Clients expect instant answers to complex questions',
			solution: 'AI-powered analysis that turns data into insights clients actually understand'
		},
		{
			role: 'Developers',
			icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4',
			problem: 'Guessing at pricing and delivery timing',
			solution: "Real-time competitive intelligence—see exactly what's launching, when, and at what price"
		}
	];

	const stats = [
		{
			value: '50K+',
			label: 'Transactions tracked',
			icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z'
		},
		{
			value: '200+',
			label: 'Projects monitored',
			icon: 'M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4'
		},
		{
			value: '10x',
			label: 'Faster than spreadsheets',
			icon: 'M13 10V3L4 14h7v7l9-11h-7z'
		}
	];

	const capabilities = [
		{
			title: 'Transaction Analytics',
			items: ['Price trends by area & project', 'Sales velocity tracking', 'Rental yield analysis', 'Historical comparables'],
			icon: 'M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z'
		},
		{
			title: 'Supply Intelligence',
			items: ['Launch calendar & timelines', 'Unit availability tracking', 'Development pipeline', 'Area saturation analysis'],
			icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2'
		},
		{
			title: 'AI Assistant',
			items: ['Natural language queries', 'Instant market insights', 'Automated reports', 'Smart recommendations'],
			icon: 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z'
		}
	];
</script>

<svelte:head>
	<title>Vitevue - Dubai Real Estate Intelligence Platform</title>
	<meta
		name="description"
		content="Professional real estate analytics platform for Dubai market. AI-powered insights for brokers, investors, and consultants."
	/>
	<style>
		html {
			scroll-behavior: smooth;
		}
	</style>
</svelte:head>

<div class="min-h-screen bg-white overflow-hidden">
	<!-- Hero Section -->
	<section class="relative pt-20 pb-24 px-6 lg:px-8">
		<!-- Decorative elements -->
		<div class="absolute top-20 right-10 w-72 h-72 bg-gradient-to-br from-teal-100/40 to-cyan-100/40 rounded-full blur-3xl"></div>
		<div class="absolute bottom-10 left-10 w-96 h-96 bg-gradient-to-br from-blue-100/30 to-purple-100/30 rounded-full blur-3xl"></div>
22
		<div class="max-w-6xl mx-auto relative">
			<!-- Logo -->
			<div class="flex items-center gap-3 mb-12">
				<div class="w-10 h-10 bg-gradient-to-br from-teal-600 to-cyan-600 rounded-lg"></div>
				<span class="text-2xl font-bold text-slate-900">Vitevue</span>
			</div>

			{#if isVisible}
				<div in:fly={{ y: 20, duration: 600, easing: cubicOut }}>
					<div class="inline-flex items-center gap-2 px-4 py-2 bg-teal-50 border border-teal-200 rounded-full mb-8">
						<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
						</svg>
						<span class="text-sm font-semibold text-teal-900">Real-time Dubai market intelligence</span>
					</div>

					<h1 class="text-5xl sm:text-6xl lg:text-7xl font-bold text-slate-900 mb-8 tracking-tight leading-[1.08] max-w-4xl">
						Your data is talking.<br />
						<span class="text-transparent bg-clip-text bg-gradient-to-r from-teal-600 to-cyan-600">
							Are you listening?
						</span>
					</h1>

					<p class="text-xl sm:text-2xl text-slate-600 max-w-3xl mb-12 leading-relaxed">
						Stop digging through spreadsheets. Start asking questions. Get instant answers from 50,000+ Dubai transactions.
					</p>

					<div class="flex flex-col sm:flex-row gap-4 mb-20">
						<a
							href="mailto:contact@vitevue.com"
							class="group inline-flex items-center justify-center gap-2 px-8 py-4 bg-gradient-to-r from-teal-600 to-cyan-600 text-white font-semibold rounded-xl hover:from-teal-700 hover:to-cyan-700 transition-all shadow-lg shadow-teal-500/25 text-base"
						>
							Talk to Sales
							<svg class="w-5 h-5 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
							</svg>
						</a>
						<a
							href="/dashboard"
							class="inline-flex items-center justify-center px-8 py-4 bg-white text-slate-900 font-semibold rounded-xl hover:bg-slate-50 transition-all border-2 border-slate-200 text-base"
						>
							See the Platform
						</a>
					</div>

					<!-- Stats with icons -->
					<div class="grid grid-cols-1 sm:grid-cols-3 gap-8 max-w-3xl">
						{#each stats as stat, i}
							<div in:fly={{ y: 20, duration: 600, delay: 400 + (i * 100), easing: cubicOut }} class="flex items-start gap-4">
								<div class="flex-shrink-0 w-12 h-12 bg-gradient-to-br from-slate-100 to-slate-50 rounded-lg flex items-center justify-center border border-slate-200">
									<svg class="w-6 h-6 text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={stat.icon}></path>
									</svg>
								</div>
								<div>
									<div class="text-3xl font-bold text-slate-900 mb-1">{stat.value}</div>
									<div class="text-sm text-slate-600">{stat.label}</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	</section>

	<!-- Features Section -->
	<section class="relative py-24 px-6 lg:px-8 bg-slate-50">
		<div class="max-w-6xl mx-auto">
			<div class="text-center mb-20">
				<div class="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-full mb-6">
					<svg class="w-4 h-4 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"></path>
					</svg>
					<span class="text-sm font-semibold text-slate-700">Platform Features</span>
				</div>
				<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-5">
					Stop searching. Start knowing.
				</h2>
				<p class="text-xl text-slate-600 max-w-2xl mx-auto">
					Everything you need to make confident real estate decisions
				</p>
			</div>

			<div class="grid md:grid-cols-2 gap-6">
				{#each features as feature, i}
					{#if isVisible}
						<div
							in:fly={{ y: 20, duration: 600, delay: i * 100, easing: cubicOut }}
							class="group relative bg-white p-8 rounded-2xl border border-slate-200 hover:border-slate-300 transition-all hover:shadow-xl"
						>
							<!-- Accent decoration -->
							<div class="absolute top-0 left-0 w-1 h-16 bg-gradient-to-b {feature.color} rounded-tl-2xl rounded-br-2xl"></div>

							<div class="flex items-start gap-5 mb-5">
								<div class="flex-shrink-0 w-14 h-14 {feature.iconBg} rounded-xl flex items-center justify-center border border-slate-200">
									<svg class="w-7 h-7 {feature.iconColor}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={feature.icon}></path>
									</svg>
								</div>
								<div class="flex-1">
									<h3 class="text-xl font-bold text-slate-900 mb-2">{feature.title}</h3>
								</div>
							</div>
							<p class="text-slate-600 leading-relaxed text-base">{feature.description}</p>
						</div>
					{/if}
				{/each}
			</div>
		</div>
	</section>

	<!-- Use Cases Section -->
	<section class="relative py-24 px-6 lg:px-8 bg-white">
		<!-- Decorative background -->
		<div class="absolute inset-0 bg-gradient-to-b from-white via-slate-50/50 to-white"></div>

		<div class="max-w-6xl mx-auto relative">
			<div class="text-center mb-16">
				<div class="inline-flex items-center gap-2 px-4 py-2 bg-slate-100 border border-slate-200 rounded-full mb-6">
					<svg class="w-4 h-4 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"></path>
					</svg>
					<span class="text-sm font-semibold text-slate-700">Who We Serve</span>
				</div>
				<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-5">
					Built for people who need answers
				</h2>
				<p class="text-xl text-slate-600 max-w-2xl mx-auto">
					Different challenges. One platform.
				</p>
			</div>

			<div class="grid md:grid-cols-2 gap-6">
				{#each useCases as useCase, i}
					{#if isVisible}
						<div
							in:fly={{ y: 20, duration: 600, delay: i * 100, easing: cubicOut }}
							class="group bg-white p-8 rounded-2xl border-2 border-slate-200 hover:border-teal-200 transition-all hover:shadow-lg"
						>
							<div class="flex items-start gap-4 mb-6">
								<div class="flex-shrink-0 w-12 h-12 bg-gradient-to-br from-slate-900 to-slate-700 rounded-xl flex items-center justify-center">
									<svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={useCase.icon}></path>
									</svg>
								</div>
								<h3 class="text-xl font-bold text-slate-900 pt-2">{useCase.role}</h3>
							</div>

							<div class="space-y-4">
								<div>
									<div class="flex items-center gap-2 mb-2">
										<svg class="w-5 h-5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
										</svg>
										<span class="text-sm font-semibold text-slate-500 uppercase tracking-wide">The Problem</span>
									</div>
									<p class="text-slate-700 leading-relaxed pl-7">{useCase.problem}</p>
								</div>
								<div>
									<div class="flex items-center gap-2 mb-2">
										<svg class="w-5 h-5 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
										</svg>
										<span class="text-sm font-semibold text-slate-500 uppercase tracking-wide">The Solution</span>
									</div>
									<p class="text-slate-900 leading-relaxed font-medium pl-7">{useCase.solution}</p>
								</div>
							</div>
						</div>
					{/if}
				{/each}
			</div>
		</div>
	</section>

	<!-- Capabilities Section -->
	<section class="py-24 px-6 lg:px-8 bg-slate-50">
		<div class="max-w-6xl mx-auto">
			<div class="text-center mb-16">
				<div class="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-full mb-6">
					<svg class="w-4 h-4 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path>
					</svg>
					<span class="text-sm font-semibold text-slate-700">What's Inside</span>
				</div>
				<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-5">
					All the data you need.<br />None you don't.
				</h2>
				<p class="text-xl text-slate-600 max-w-2xl mx-auto">
					Three powerful modules that work together
				</p>
			</div>

			<div class="grid md:grid-cols-3 gap-6">
				{#each capabilities as capability, i}
					{#if isVisible}
						<div
							in:fly={{ y: 20, duration: 600, delay: i * 100, easing: cubicOut }}
							class="bg-white p-8 rounded-2xl border border-slate-200 hover:border-slate-300 transition-all"
						>
							<div class="w-14 h-14 bg-gradient-to-br from-teal-50 to-cyan-50 rounded-xl flex items-center justify-center mb-6 border border-teal-100">
								<svg class="w-7 h-7 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={capability.icon}></path>
								</svg>
							</div>
							<h3 class="text-xl font-bold text-slate-900 mb-4">{capability.title}</h3>
							<ul class="space-y-3">
								{#each capability.items as item}
									<li class="flex items-start gap-3 text-slate-600">
										<svg class="w-5 h-5 text-teal-600 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
										</svg>
										<span class="text-sm leading-relaxed">{item}</span>
									</li>
								{/each}
							</ul>
						</div>
					{/if}
				{/each}
			</div>
		</div>
	</section>

	<!-- Platform Preview -->
	<section class="relative py-24 px-6 lg:px-8 bg-gradient-to-b from-white to-slate-50">
		<div class="max-w-5xl mx-auto">
			<div class="text-center mb-12">
				<h2 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-5">
					See it in action
				</h2>
				<p class="text-xl text-slate-600 max-w-2xl mx-auto">
					Clean interface. Powerful analytics. Zero learning curve.
				</p>
			</div>

			<div class="relative bg-white rounded-3xl border-2 border-slate-200 p-2 shadow-2xl overflow-hidden">
				<!-- Browser chrome -->
				<div class="flex items-center gap-2 px-4 py-3 bg-slate-50 border-b border-slate-200 rounded-t-2xl">
					<div class="flex gap-2">
						<div class="w-3 h-3 rounded-full bg-red-400"></div>
						<div class="w-3 h-3 rounded-full bg-yellow-400"></div>
						<div class="w-3 h-3 rounded-full bg-green-400"></div>
					</div>
					<div class="flex-1 mx-4 px-4 py-1.5 bg-white rounded-lg border border-slate-200">
						<span class="text-xs text-slate-500">app.vitevue.com/dashboard</span>
					</div>
				</div>

				<!-- Screenshot placeholder with visual elements -->
				<div class="aspect-video bg-gradient-to-br from-slate-100 via-slate-50 to-white rounded-b-2xl relative overflow-hidden">
					<div class="absolute inset-0 flex items-center justify-center">
						<div class="text-center p-12">
							<div class="w-20 h-20 bg-gradient-to-br from-teal-500 to-cyan-600 rounded-2xl flex items-center justify-center mx-auto mb-6 shadow-lg">
								<svg class="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
								</svg>
							</div>
							<p class="text-slate-400 font-medium text-lg">Dashboard preview</p>
							<p class="text-slate-300 text-sm mt-2">Request a demo to see the platform live</p>
						</div>
					</div>
					<!-- Decorative grid -->
					<div class="absolute inset-0 opacity-10">
						<div class="grid grid-cols-8 grid-rows-6 h-full">
							{#each Array(48) as _, i}
								<div class="border border-slate-300"></div>
							{/each}
						</div>
					</div>
				</div>
			</div>
		</div>
	</section>

	<!-- CTA Section -->
	<section class="relative py-32 px-6 lg:px-8 bg-gradient-to-b from-slate-50 to-white">
		<!-- Decorative elements -->
		<div class="absolute top-20 left-1/4 w-64 h-64 bg-gradient-to-br from-teal-100/30 to-cyan-100/30 rounded-full blur-3xl"></div>
		<div class="absolute bottom-20 right-1/4 w-80 h-80 bg-gradient-to-br from-blue-100/20 to-purple-100/20 rounded-full blur-3xl"></div>

		<div class="max-w-4xl mx-auto text-center relative">
			<div class="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-full mb-8">
				<svg class="w-4 h-4 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z"></path>
				</svg>
				<span class="text-sm font-semibold text-slate-700">Get Started</span>
			</div>

			<h2 class="text-4xl sm:text-5xl lg:text-6xl font-bold text-slate-900 mb-6">
				Stop guessing.<br />Start knowing.
			</h2>
			<p class="text-xl text-slate-600 mb-12 max-w-2xl mx-auto leading-relaxed">
				Join the brokers, investors, and consultants who've already ditched their spreadsheets
			</p>

			<div class="flex flex-col sm:flex-row gap-5 justify-center mb-12">
				<a
					href="mailto:contact@vitevue.com"
					class="group inline-flex items-center justify-center gap-2 px-10 py-5 bg-gradient-to-r from-teal-600 to-cyan-600 text-white font-bold rounded-xl hover:from-teal-700 hover:to-cyan-700 transition-all shadow-xl shadow-teal-500/25 text-lg"
				>
					Schedule a Demo
					<svg class="w-5 h-5 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
					</svg>
				</a>
				<a
					href="/dashboard"
					class="inline-flex items-center justify-center px-10 py-5 bg-white text-slate-900 font-bold rounded-xl hover:bg-slate-50 transition-all border-2 border-slate-200 text-lg"
				>
					Explore Platform
				</a>
			</div>

			<!-- Trust indicators -->
			<div class="flex flex-wrap items-center justify-center gap-8 pt-8 border-t border-slate-200">
				<div class="flex items-center gap-2 text-slate-600">
					<svg class="w-5 h-5 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path>
					</svg>
					<span class="text-sm font-medium">Enterprise-grade security</span>
				</div>
				<div class="flex items-center gap-2 text-slate-600">
					<svg class="w-5 h-5 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
					</svg>
					<span class="text-sm font-medium">Real-time data updates</span>
				</div>
				<div class="flex items-center gap-2 text-slate-600">
					<svg class="w-5 h-5 text-teal-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z"></path>
					</svg>
					<span class="text-sm font-medium">Dedicated support</span>
				</div>
			</div>
		</div>
	</section>

	<!-- Footer -->
	<footer class="relative border-t border-slate-200 bg-white">
		<div class="max-w-6xl mx-auto px-6 lg:px-8 py-16">
			<div class="grid md:grid-cols-4 gap-12 mb-12">
				<!-- Brand -->
				<div class="md:col-span-1">
					<div class="flex items-center gap-3 mb-4">
						<div class="w-10 h-10 bg-gradient-to-br from-teal-600 to-cyan-600 rounded-lg"></div>
						<span class="text-xl font-bold text-slate-900">Vitevue</span>
					</div>
					<p class="text-sm text-slate-600 leading-relaxed">
						Dubai's real estate intelligence platform
					</p>
				</div>

				<!-- Product -->
				<div>
					<h4 class="text-sm font-bold text-slate-900 uppercase tracking-wide mb-4">Product</h4>
					<ul class="space-y-3">
						<li><a href="/dashboard" class="text-sm text-slate-600 hover:text-teal-600 transition-colors">Dashboard</a></li>
						<li><a href="/transactions" class="text-sm text-slate-600 hover:text-teal-600 transition-colors">Transactions</a></li>
						<li><a href="/analytics" class="text-sm text-slate-600 hover:text-teal-600 transition-colors">Analytics</a></li>
						<li><a href="/supply" class="text-sm text-slate-600 hover:text-teal-600 transition-colors">Supply</a></li>
					</ul>
				</div>

				<!-- Company -->
				<div>
					<h4 class="text-sm font-bold text-slate-900 uppercase tracking-wide mb-4">Company</h4>
					<ul class="space-y-3">
						<li><a href="/about" class="text-sm text-slate-600 hover:text-teal-600 transition-colors">About</a></li>
						<li><a href="mailto:contact@vitevue.com" class="text-sm text-slate-600 hover:text-teal-600 transition-colors">Contact</a></li>
					</ul>
				</div>

				<!-- Connect -->
				<div>
					<h4 class="text-sm font-bold text-slate-900 uppercase tracking-wide mb-4">Connect</h4>
					<p class="text-sm text-slate-600 mb-4">Get in touch with our team</p>
					<a
						href="mailto:contact@vitevue.com"
						class="inline-flex items-center gap-2 text-sm font-semibold text-teal-600 hover:text-teal-700 transition-colors"
					>
						contact@vitevue.com
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
						</svg>
					</a>
				</div>
			</div>

			<div class="pt-8 border-t border-slate-200 flex flex-col md:flex-row justify-between items-center gap-4">
				<p class="text-sm text-slate-500">
					&copy; 2026 Vitevue. All rights reserved.
				</p>
				<div class="flex gap-6">
					<a href="/privacy" class="text-sm text-slate-500 hover:text-slate-900 transition-colors">Privacy</a>
					<a href="/terms" class="text-sm text-slate-500 hover:text-slate-900 transition-colors">Terms</a>
				</div>
			</div>
		</div>
	</footer>
</div>

<style>
	:global(body) {
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
	}
</style>
