<script lang="ts">
import AuthStepBadge from './AuthStepBadge.svelte'

export let title: string
export let description = ''
export let eyebrow = 'Vitevue'
export let step = ''
export let totalSteps = 0
export let stepLabel = ''
export let sideTitle = ''
export let sideCopy = ''
export let sideAccent = 'Guided onboarding'
export let contentWidthClass = 'max-w-2xl'
export let sectionWidthClass = 'lg:max-w-xl xl:max-w-2xl'
export let cardClass = ''
export let bodyClass = ''
</script>

<svelte:head>
	<meta name="viewport" content="width=device-width, initial-scale=1" />
</svelte:head>

<div class="min-h-screen overflow-hidden bg-[var(--color-bg-marketing)] px-4 py-4 sm:px-6 lg:px-8">
	<div class="mx-auto flex min-h-[calc(100vh-2rem)] max-w-7xl items-stretch gap-4">
		<section
			class="relative hidden flex-1 overflow-hidden rounded-lg border border-[rgba(246,241,231,0.16)] bg-[var(--color-navy-900)] p-8 text-[var(--color-fg-on-navy)] lg:flex lg:flex-col lg:justify-between lg:gap-8 xl:p-10"
		>
			<img
				src="/logos/icon-bone.svg"
				alt=""
				class="pointer-events-none absolute -right-20 -top-16 h-72 w-72 opacity-[0.035]"
				aria-hidden="true"
			/>
			<div class="relative">
				<p
					class="inline-flex items-center gap-3 font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--color-fg-on-navy-muted)] before:h-px before:w-7 before:bg-current"
				>
					{sideAccent}
				</p>
				{#if sideTitle}
					<h2
						class="mt-5 max-w-xl font-display text-[2.3rem] font-normal leading-[1.04] tracking-[var(--tracking-display)] xl:text-[2.7rem]"
					>
						{sideTitle}
					</h2>
				{/if}
				{#if sideCopy}
					<p class="mt-5 max-w-lg text-sm leading-6 text-[var(--color-fg-on-navy-muted)]">
						{sideCopy}
					</p>
				{/if}
			</div>

			<div class="relative pb-1">
				<slot name="side" />
			</div>
		</section>

		<section class={`flex h-full w-full items-stretch justify-center ${sectionWidthClass}`}>
			<div
				class={`flex min-h-[calc(100vh-2rem)] w-full ${contentWidthClass} flex-col rounded-lg border border-[var(--color-border-warm)] bg-white p-5 shadow-sm sm:p-6 lg:p-8 ${cardClass}`}
			>
				<div class="flex h-full flex-col gap-4">
					<div class="flex flex-wrap items-center justify-between gap-4">
						<div class="space-y-5">
							<img
								src="/logos/vitevue-navbar-800@2x.png"
								alt="Vitevue"
								class="h-6 w-auto"
							/>
							<p
								class="inline-flex items-center gap-3 font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--color-fg-4)] before:h-px before:w-7 before:bg-current"
							>
								{eyebrow}
							</p>
						</div>
						{#if step}
							<AuthStepBadge {step} total={totalSteps} label={stepLabel} />
						{/if}
					</div>

					<slot name="account" />

					<div class="min-h-[4.75rem]">
						<h1
							class="max-w-2xl font-display text-[2.15rem] font-normal leading-[1.08] tracking-[var(--tracking-display)] text-[var(--color-fg-1)] sm:text-[2.55rem]"
						>
							{title}
						</h1>
						{#if description}
							<p class="mt-2 max-w-2xl text-sm leading-6 text-[var(--color-fg-3)] sm:text-base">
								{description}
							</p>
						{/if}
					</div>

					<div class={`flex-1 space-y-5 ${bodyClass}`}>
						<slot />
					</div>
				</div>
			</div>
		</section>
	</div>
</div>
