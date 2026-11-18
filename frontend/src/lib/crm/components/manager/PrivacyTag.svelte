<script lang="ts">
import InfoTip from '$lib/crm/components/ui/InfoTip.svelte'
import { PRIVACY, type PrivacyKey, type ViewAs } from '$lib/crm/mock/manager'

/**
 * Marks a field whose visibility is still an open question (context.md privacy matrix). Hover or
 * focus shows what each account type sees; the line for the current view is bold.
 */
let {
	k,
	view,
	name
}: {
	k: PrivacyKey
	view: ViewAs
	/** Tells two tags side by side apart, e.g. "phone/email" and "contacts". */
	name?: string
} = $props()
const p = $derived(PRIVACY[k])

/**
 * Open the box towards the middle of the screen: a tag in the right half opens leftwards, so a
 * tag at a card's right edge doesn't push its box off screen. Set on pointer enter / focus
 * (capture), which run before InfoTip's own handlers read `align`.
 */
let align = $state<'left' | 'right'>('left')
function pickSide(e: Event) {
	const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
	align = r.left + r.width / 2 > window.innerWidth / 2 ? 'right' : 'left'
}
</script>

<span class="ptag" role="none" onpointerenter={pickSide} onfocuscapture={pickSide}>
	<InfoTip label="Privacy: {p.label}" glyph={name ? `privacy · ${name}` : 'privacy'} {align}>
		<b>{p.label}</b>
		<span class:now={view === 'agent'}>Agent sees: {p.agent}</span>
		<span class:now={view === 'manager'}>Manager sees: {p.manager}</span>
		<span class="q">Open question for the review call.</span>
	</InfoTip>
</span>

<style>
	.ptag {
		display: inline-flex;
		vertical-align: middle;
	}
	/* Dashed outline: "not decided yet". */
	.ptag :global(.itip) {
		font-size: 11px;
		font-weight: 500;
		padding: 0 7px;
		border: 1px dashed var(--sep-strong);
		border-radius: 999px;
	}
	.now {
		font-weight: 600;
	}
	.q {
		color: var(--text2);
		font-size: 12px;
	}
</style>
