<script lang="ts">
import type { Status } from './data'

/** Screen status (Live, Being fixed, In build, Not yet) and its tier, next to the title. */
let { status, tier = '' }: { status: Status; tier?: string } = $props()

const TONE: Record<Status, string> = {
	Live: 'mk-ok',
	'Being fixed': 'mk-fix',
	'In build': 'mk-neu',
	'Not yet': 'mk-bad'
}
</script>

<span class="mk-badges">
	<span class={['mk-tag', TONE[status]]}>{status}</span>
	{#each tier ? tier.split(' / ') : [] as t (t)}<span class="mk-tier">{t}</span>{/each}
</span>
