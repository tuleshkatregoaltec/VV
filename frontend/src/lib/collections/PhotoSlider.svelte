<script lang="ts">
/**
 * Listing photo slider: arrows, dots, swipe and arrow keys; auto-advances while hovered
 * (never when the viewer prefers reduced motion). Photos that fail to load are dropped.
 * `controls={false}` drops the arrow buttons, swipe and keys, for use inside a clickable card.
 */
let {
	photos = [],
	empty = 'No photo',
	interval = 3000,
	controls = true
}: { photos?: string[]; empty?: string; interval?: number; controls?: boolean } = $props()

let broken = $state<string[]>([])
let index = $state(0)
let hovering = $state(false)
let startX: number | null = null

const shown = $derived(photos.filter((p) => !broken.includes(p)))
const count = $derived(shown.length)
const current = $derived(count ? index % count : 0)

function go(step: number, e?: Event) {
	e?.stopPropagation()
	e?.preventDefault()
	if (count > 1) index = (current + step + count) % count
}

function fail(src: string) {
	if (!broken.includes(src)) broken = [...broken, src]
}

$effect(() => {
	if (!hovering || count < 2) return
	if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
	const timer = setInterval(() => go(1), interval)
	return () => clearInterval(timer)
})
</script>

{#if count}
	<!-- The Previous/Next buttons are the accessible controls; hover, swipe and arrow keys are extras. -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="slider"
		role="group"
		aria-roledescription="carousel"
		aria-label={`Photo ${current + 1} of ${count}`}
		tabindex="-1"
		onmouseenter={() => (hovering = true)}
		onmouseleave={() => (hovering = false)}
		onfocusin={() => (hovering = true)}
		onfocusout={() => (hovering = false)}
		onkeydown={(e) => {
			if (!controls) return
			if (e.key === 'ArrowLeft') go(-1, e)
			if (e.key === 'ArrowRight') go(1, e)
		}}
		ontouchstart={(e) => (startX = controls ? (e.touches[0]?.clientX ?? null) : null)}
		ontouchend={(e) => {
			const endX = e.changedTouches[0]?.clientX
			if (startX != null && endX != null && Math.abs(endX - startX) > 40) go(endX < startX ? 1 : -1)
			startX = null
		}}
	>
		<div class="track" style:transform={`translateX(-${current * 100}%)`}>
			{#each shown as src, i (src)}
				<img
					{src}
					alt=""
					loading={i === 0 ? 'eager' : 'lazy'}
					referrerpolicy="no-referrer"
					draggable="false"
					onerror={() => fail(src)}
				/>
			{/each}
		</div>

		{#if count > 1}
			{#if controls}
			<button type="button" class="nav prev" aria-label="Previous photo" onclick={(e) => go(-1, e)}
				>‹</button
			>
			<button type="button" class="nav next" aria-label="Next photo" onclick={(e) => go(1, e)}
				>›</button
			>
			{/if}
			<span class="counter">{current + 1} / {count}</span>
			<span class="dots" aria-hidden="true">
				{#each shown as src, i (src)}
					<span class:on={i === current}></span>
				{/each}
			</span>
		{/if}
	</div>
{:else}
	<span class="none">
		<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11.5 12 4l9 7.5M5.5 9.5V20h13V9.5" /></svg>
		{empty}
	</span>
{/if}

<style>
	.slider { position: absolute; inset: 0; overflow: hidden; outline: none; touch-action: pan-y; }
	.track { display: flex; height: 100%; transition: transform 0.45s cubic-bezier(0.22, 0.8, 0.3, 1); }
	.track img { flex: 0 0 100%; width: 100%; height: 100%; object-fit: cover; display: block; user-select: none; }
	@media (prefers-reduced-motion: reduce) { .track { transition: none; } }

	.nav {
		position: absolute; top: 50%; z-index: 2; width: 32px; height: 32px; margin-top: -16px;
		border: 0; border-radius: 50%; cursor: pointer; display: grid; place-items: center;
		font-size: 22px; line-height: 1; padding-bottom: 2px;
		background: rgba(255, 255, 255, 0.92); color: #0a1422; box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
		opacity: 0; transition: opacity 0.15s, transform 0.15s;
	}
	.prev { left: 10px; }
	.next { right: 10px; }
	.slider:hover .nav, .nav:focus-visible { opacity: 1; }
	.nav:hover { transform: scale(1.08); }
	@media (hover: none) { .nav { opacity: 0.85; } }

	.counter {
		position: absolute; left: 10px; top: 10px; z-index: 2; padding: 3px 8px; border-radius: 999px;
		font-size: 11px; font-weight: 600; background: rgba(5, 10, 18, 0.6); color: #fff; backdrop-filter: blur(4px);
	}
	.dots { position: absolute; right: 12px; bottom: 14px; z-index: 2; display: flex; gap: 5px; }
	.dots span {
		width: 6px; height: 6px; border-radius: 999px; background: rgba(255, 255, 255, 0.55);
		transition: width 0.2s, background 0.2s;
	}
	.dots span.on { width: 16px; background: #fff; }

	.none {
		position: absolute; inset: 0; display: grid; place-content: center; justify-items: center; gap: 6px;
		color: var(--color-fg-4, #64748b); font-size: 12px;
	}
	.none svg { width: 28px; height: 28px; fill: none; stroke: currentColor; stroke-width: 1.5; }
</style>
