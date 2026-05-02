<script lang="ts">
function scrollToPreview() {
	document.getElementById('preview')?.scrollIntoView({ behavior: 'smooth' })
}
</script>

<section class="bg-bone">
	<div class="mx-auto max-w-7xl px-5 py-20 sm:px-8 sm:py-24 lg:px-10 lg:py-28">
		<div class="grid items-center gap-14 lg:grid-cols-[1.1fr_0.9fr] lg:gap-20">
			<div>
				<span class="eyebrow">Built for Dubai</span>
				<h1 class="display-1 mt-7 max-w-4xl">
					Real estate intelligence,<br />
					<span class="display-italic">made for Dubai.</span>
				</h1>
				<p class="mt-7 max-w-xl text-lg leading-[1.6] text-[var(--color-fg-2)] sm:text-xl">
					Operate with an edge; shorter cycles, sharper pitches, more deals. Vitevue reads
					decades of macro data and 10M+ transactions so you do not have to.
				</p>
				<div class="mt-9 flex flex-col gap-3 sm:flex-row">
					<a
						href="/auth"
						class="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-7 py-4 text-sm font-medium text-bone transition-colors duration-200 hover:bg-primary-light"
					>
						Get started
						<svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M13 7l5 5m0 0l-5 5m5-5H6"
							/>
						</svg>
					</a>
					<button
						type="button"
						onclick={scrollToPreview}
						class="inline-flex items-center justify-center rounded-md border border-primary bg-transparent px-7 py-4 text-sm font-medium text-primary transition-colors duration-200 hover:bg-primary hover:text-bone"
					>
						See platform
					</button>
				</div>
			</div>

			<div
				class="relative flex aspect-[4/5] flex-col justify-between overflow-hidden rounded-lg bg-primary p-8 text-bone shadow-[var(--shadow-lg)]"
			>
				<img src="/logos/icon-bone.svg" alt="" class="absolute right-7 top-7 h-8 w-8" />
				<div class="font-mono text-[11px] uppercase tracking-[0.06em] text-bone/50">
					/ 01 - Q3 2025 snapshot
				</div>
				<div>
					<div class="font-display text-[clamp(3.5rem,8vw,5.75rem)] leading-none tracking-[-0.025em]">
						+22<span class="display-italic">bps</span>
					</div>
					<p class="mt-3 max-w-xs text-sm leading-relaxed text-bone/70">
						Marina 2BR net yields, QoQ. 147 transactions across 9 towers.
					</p>
				</div>
			</div>
		</div>

		<div class="mt-20 grid border-y border-bone-border sm:grid-cols-3">
			<div class="border-b border-bone-border py-8 sm:border-b-0 sm:border-r sm:pr-8">
				<div class="font-display text-5xl leading-none tracking-[-0.025em] text-[var(--color-fg-1)]">
					10M+
				</div>
				<div class="mt-2 text-sm text-[var(--color-fg-3)]">Transactions analysed</div>
			</div>
			<div class="border-b border-bone-border py-8 sm:border-b-0 sm:border-r sm:px-8">
				<div class="font-display text-5xl leading-none tracking-[-0.025em] text-[var(--color-fg-1)]">
					3,000<span class="text-3xl">+</span>
				</div>
				<div class="mt-2 text-sm text-[var(--color-fg-3)]">Projects tracked</div>
			</div>
			<div class="py-8 sm:pl-8">
				<div class="font-display text-5xl leading-none tracking-[-0.025em] text-[var(--color-fg-1)]">
					15<span class="ml-1 text-2xl">yrs</span>
				</div>
				<div class="mt-2 text-sm text-[var(--color-fg-3)]">Macro data depth</div>
			</div>
		</div>
	</div>
</section>
