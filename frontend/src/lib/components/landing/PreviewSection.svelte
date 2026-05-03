<script lang="ts">
const features = [
	{
		eyebrow: 'AI-powered',
		title: 'Ask anything,',
		accent: 'get instant answers.',
		copy: 'Stop searching. Start asking. Vitevue AI reads decades of macro data and 10M+ transactions to answer pricing, yield, and feasibility questions in seconds, with the comp basket and source files attached.',
		image: '/images/chat.png',
		alt: 'Vitevue AI chat',
		bullets: [
			'Quarter-on-quarter yield, price, and supply queries',
			'Auto-generated listing descriptions and pitch decks',
			'Cited sources on every answer'
		]
	},
	{
		eyebrow: 'Export-ready',
		title: 'Your premium',
		accent: 'radar system.',
		copy: 'Compare any target project against a defensible comps set, built manually or auto-matched via our proprietary comparables algorithm. Review everything in a matched KPI grid, then export a client-ready evidence pack in one click.',
		image: '/images/transactions.png',
		alt: 'Vitevue transactions',
		reverse: true,
		bullets: [
			'Auto-matched and manual comp sets',
			'Live KPI grid with field-flash on changes',
			'One-click PDF and Excel evidence packs'
		]
	},
	{
		eyebrow: 'Visual data',
		title: 'Decades of macro,',
		accent: 'decoded.',
		copy: 'Pricing dynamics, supply pipeline, configuration mix, and yield curves, all sourced from the same transaction stack. Pressure-test feasibility in minutes instead of days.',
		image: '/images/analytics.png',
		alt: 'Vitevue analytics',
		bullets: [
			'Supply pipeline and absorption curves',
			'Configuration opportunity heatmaps',
			'Net yield and cap rate by sub-market'
		]
	}
]
</script>

<section id="preview" class="bg-bone py-24 lg:py-28">
	<div class="mx-auto max-w-7xl px-5 sm:px-8 lg:px-10">
		<div class="mb-20 max-w-3xl">
			<span class="eyebrow">Platform overview</span>
			<h2 class="display-2 mt-6">
				Tactical comps, <span class="display-italic">institutional outputs.</span>
			</h2>
		</div>

		<div>
			{#each features as feature, index (feature.eyebrow)}
				<article
					class="grid items-center gap-10 border-t border-bone-border py-14 lg:grid-cols-[1fr_1.15fr] lg:gap-20"
				>
					<div class={feature.reverse ? 'lg:order-2' : ''}>
						<span class="eyebrow">{feature.eyebrow}</span>
						<h3
							class="mt-4 font-display text-[clamp(2.5rem,5vw,3.75rem)] font-normal leading-[1.05] tracking-[-0.025em] text-fg-1"
						>
							{feature.title}
							<span class="display-italic">{feature.accent}</span>
						</h3>
						<p class="mt-5 max-w-xl text-[17px] leading-[1.65] text-fg-2">
							{feature.copy}
						</p>
						<ul class="mt-6 space-y-3">
							{#each feature.bullets as bullet (bullet)}
								<li class="flex items-start gap-3 text-[15px] leading-relaxed text-fg-2">
									<svg
										class="mt-1 h-4 w-4 flex-none text-primary"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2.5"
											d="M5 13l4 4L19 7"
										/>
									</svg>
									<span>{bullet}</span>
								</li>
							{/each}
						</ul>
					</div>

					<div
						class="aspect-[16/9] overflow-hidden rounded-lg border border-bone-border bg-white p-4 shadow-[var(--shadow-md)] {feature.reverse
							? 'lg:order-1'
							: ''}"
					>
						<img
							src={feature.image}
							alt={feature.alt}
							class="h-full w-full rounded-sm border border-slate-200 object-cover object-top"
							loading="eager"
						/>
					</div>
				</article>
			{/each}
		</div>
	</div>
</section>
