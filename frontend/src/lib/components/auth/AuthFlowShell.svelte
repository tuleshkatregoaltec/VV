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

<div
	class="min-h-screen overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(148,163,184,0.14),_transparent_32%),linear-gradient(180deg,#f8fafc_0%,#eef2ff_42%,#f8fafc_100%)] px-4 py-4 sm:px-6 lg:px-8"
>
	<div class="mx-auto flex h-[calc(100vh-2rem)] max-w-7xl items-stretch gap-4">
		<section
			class="relative hidden flex-1 overflow-hidden rounded-[2rem] border border-slate-200/70 bg-slate-950 p-6 text-white shadow-[0_24px_80px_rgba(15,23,42,0.18)] lg:flex lg:flex-col lg:gap-8"
		>
			<div
				class="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(59,130,246,0.28),_transparent_26%),radial-gradient(circle_at_bottom_left,_rgba(16,185,129,0.18),_transparent_34%)]"
			></div>
			<div class="relative">
				<p class="text-xs font-semibold uppercase tracking-[0.32em] text-slate-300">{sideAccent}</p>
				{#if sideTitle}
					<h2 class="mt-4 max-w-md text-[2rem] font-semibold leading-tight">{sideTitle}</h2>
				{/if}
				{#if sideCopy}
					<p class="mt-4 max-w-lg text-sm leading-6 text-slate-300">{sideCopy}</p>
				{/if}
			</div>

			<div class="relative">
				<slot name="side" />
			</div>
		</section>

		<section class={`flex h-full w-full items-stretch justify-center ${sectionWidthClass}`}>
			<div
				class={`flex h-full w-full ${contentWidthClass} flex-col rounded-[2rem] border border-white/70 bg-white/88 p-6 shadow-[0_24px_70px_rgba(148,163,184,0.18)] backdrop-blur sm:p-6 lg:p-7 ${cardClass}`}
			>
				<div class="flex h-full flex-col gap-4">
					<div class="flex flex-wrap items-center justify-between gap-4">
						<div>
							<p class="text-xs font-semibold uppercase tracking-[0.32em] text-slate-500">
								{eyebrow}
							</p>
						</div>
						{#if step}
							<AuthStepBadge {step} total={totalSteps} label={stepLabel} />
						{/if}
					</div>

					<slot name="account" />

					<div class="min-h-[4.75rem]">
						<h1 class="max-w-2xl text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
							{title}
						</h1>
						{#if description}
							<p class="mt-2 max-w-2xl text-sm leading-6 text-slate-600 sm:text-base">
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
