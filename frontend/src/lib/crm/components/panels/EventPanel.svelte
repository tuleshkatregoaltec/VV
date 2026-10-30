<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { getQueryClient } from '$lib/queries/client'
import { crm } from '../../api'
import type { CalendarEvent } from '../../api/types'
import { EVENT_KINDS } from '../../config'
import { dayLabel, fullDate } from '../../format'
import { crmKeys, crmQueries } from '../../queries'
import { openRef, panel } from '../../stores/panel.svelte'
import { write } from '../../write'
import Kv from '../ui/Kv.svelte'
import Panel from '../ui/Panel.svelte'
import PanelLoading from '../ui/PanelLoading.svelte'

/**
 * Event detail (7 Oct): when, kind, detail, linked record, outcome. Open record, Edit (full form,
 * synced to Google Calendar), Reschedule
 * (a lead's event is logged on the lead and becomes its next action) and Delete, each with Undo.
 */
let { id }: { id: number } = $props()
const event = createQuery(() => crmQueries.event(id))
const me = createQuery(() => crmQueries.me())

let moving = $state(false)
let date = $state('')
let time = $state('')

function startMove() {
	const e = event.data
	if (!e) return
	date = e.date < (me.data?.today ?? '') ? (me.data?.today ?? e.date) : e.date
	time = e.time ?? ''
	moving = true
}

async function reschedule(e: SubmitEvent) {
	e.preventDefault()
	const r = await write({
		call: () => crm.events.reschedule(id, date, time || null),
		success: (res) =>
			`Moved to ${dayLabel(res.data.date)}${res.data.time ? ` ${res.data.time}` : ''}`
	})
	if (r) moving = false
}

/** Take the event off every cached calendar range now; the refetch after the write can be slow. */
function dropFromCalendar() {
	const qc = getQueryClient()
	const key = [...crmKeys.all, 'events']
	const before = qc.getQueriesData<CalendarEvent[]>({ queryKey: key })
	void qc.cancelQueries({ queryKey: key })
	qc.setQueriesData<CalendarEvent[]>({ queryKey: key }, (list) => list?.filter((e) => e.id !== id))
	return () => {
		for (const [k, list] of before) qc.setQueryData(k, list)
	}
}

async function remove(title: string) {
	panel.close()
	await write({
		call: () => crm.events.remove(id),
		optimistic: dropFromCalendar,
		success: `Deleted · ${title}`
	})
}

async function done(title: string) {
	panel.close()
	await write({
		call: () => crm.events.done(id),
		optimistic: dropFromCalendar,
		success: `Done · ${title}`
	})
}
</script>

{#if event.data}
	{@const e = event.data}
	<Panel kicker={EVENT_KINDS[e.kind].label} title={e.title} sub="{fullDate(e.date)}{e.time ? ` · ${e.time}` : ''}">
		{#snippet tags()}
			<span class="dot" style:background={EVENT_KINDS[e.kind].color} style:width="10px" style:height="10px"></span>
			<span class="small muted">{EVENT_KINDS[e.kind].label}</span>
		{/snippet}
		<div class="kv">
			<Kv k="When" v="{dayLabel(e.date)}{e.all_day ? ' · all day' : ` · ${e.time ?? ''}–${e.end_time ?? ''}`}{e.end_date !== e.date ? ` → ${dayLabel(e.end_date)}` : ''}" />
			<Kv k="Kind" v={EVENT_KINDS[e.kind].label} />
			<Kv k="Repeat" v={e.repeat === 'none' ? 'Does not repeat' : e.repeat} />
			<Kv k="Show as" v={e.show_as === 'free' ? 'Free' : 'Busy'} />
			<Kv k="Location" v={e.location || '—'} />
			<Kv k="Guests" v={e.guests.join(', ') || '—'} wide />
			<Kv
				k="Guest permissions"
				v={`${e.guests_can_modify ? 'Can edit' : 'Cannot edit'} · ${e.guests_can_invite_others ? 'can invite' : 'cannot invite others'} · ${e.guests_can_see_other_guests ? 'can see guests' : 'guest list hidden'}`}
				wide
			/>
			<Kv k="Description" v={e.detail || '—'} wide />
			{#if e.meet_link}
				<Kv k="Google Meet" wide><a href={e.meet_link} target="_blank" rel="noreferrer">{e.meet_link}</a></Kv>
			{/if}
			<Kv k="Linked record" v={e.record?.label ?? 'None'} o={e.context ?? ''} />
			<Kv k="Outcome" v={e.outcome ?? '—'} />
		</div>

		{#if moving}
			<form class="form" onsubmit={reschedule}>
				<div class="frow">
					<div class="fld">
						<label for="ev-date">New date</label>
						<input id="ev-date" type="date" required min={me.data?.today} bind:value={date} />
					</div>
					<div class="fld">
						<label for="ev-time">Time</label>
						<input id="ev-time" type="time" bind:value={time} />
					</div>
				</div>
				{#if e.record?.kind === 'lead'}
					<div class="small muted">Also moves the lead's next action to this date.</div>
				{/if}
				<div class="form-actions">
					<button type="submit" class="btn">Move</button>
					<button type="button" class="btn ghost" onclick={() => (moving = false)}>Cancel</button>
				</div>
			</form>
		{/if}

		{#snippet footer()}
			{#if e.record}
				{@const rec = e.record}
				<button type="button" class="btn" onclick={() => openRef(rec)}>Open record</button>
			{/if}
			<button type="button" class="btn ghost" onclick={() => panel.open({ kind: 'edit-event', id })}>Edit</button>
			<button type="button" class="btn ghost" onclick={startMove}>Reschedule</button>
			{#if !e.record}
				<button type="button" class="btn ghost" onclick={() => done(e.title)}>Mark done</button>
			{/if}
			<button type="button" class="btn danger" onclick={() => remove(e.title)}>Delete</button>
		{/snippet}
	</Panel>
{:else}
	<PanelLoading query={event} kicker="Calendar" />
{/if}
