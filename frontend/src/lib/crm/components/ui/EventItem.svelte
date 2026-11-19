<script lang="ts">
import type { CalendarEvent } from '../../api/types'
import { eventColor, ownerLabel } from '../../calendar'
import { EVENT_KINDS } from '../../config'
import { openEvent } from '../../events'
import Chip from './Chip.svelte'

/**
 * A day's event (v2): time, kind colour bar, title, then "Buyer · Property Finder" and the unit.
 * `movedFrom` is the old time on a slot the event was rescheduled away from; shown struck through.
 * `showOwner` (manager/owner view) adds whose it is: "You" or "Aisha K · Agent".
 */
let {
	event,
	movedFrom = null,
	showOwner = !event.can_edit
}: { event: CalendarEvent; movedFrom?: string | null; showOwner?: boolean } = $props()
</script>

<button type="button" class={['li evrow', movedFrom && 'moved']} onclick={() => openEvent(event)}>
	<span class="time">{movedFrom ?? event.time ?? 'Due'}</span>
	<span class="bar" style:background={eventColor(event)} title={event.redacted ? 'Busy' : EVENT_KINDS[event.kind].label}></span>
	<span>
		<div class="t">{event.title}</div>
		{#if showOwner}
			<div class="owner">{ownerLabel(event)}</div>
		{/if}
		<div class="d">{#if event.context}{event.context}{' · '}{/if}{event.detail}</div>
	</span>
	{#if movedFrom}<Chip>Rescheduled</Chip>{:else if event.outcome === 'No outcome logged'}<Chip tone="red">No outcome</Chip>{:else}<span></span>{/if}
</button>
