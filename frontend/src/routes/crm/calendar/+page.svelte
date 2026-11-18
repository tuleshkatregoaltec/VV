<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import ArrowRight from 'lucide-svelte/icons/arrow-right'
import RefreshCw from 'lucide-svelte/icons/refresh-cw'
import { afterNavigate, replaceState } from '$app/navigation'
import { crm } from '$lib/crm/api'
import { calendarDays, googleReturn } from '$lib/crm/calendar'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import ErrorLine from '$lib/crm/components/ui/ErrorLine.svelte'
import EventItem from '$lib/crm/components/ui/EventItem.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import Skeleton from '$lib/crm/components/ui/Skeleton.svelte'
import { EVENT_KIND_ORDER, EVENT_KINDS } from '$lib/crm/config'
import { openEvent } from '$lib/crm/events'
import {
	addMonths,
	dayLabel,
	dayOfMonth,
	monthGrid,
	monthOf,
	monthTitle,
	shortDate,
	WEEKDAYS
} from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { phone } from '$lib/crm/stores/media.svelte'
import { openLead, panel } from '$lib/crm/stores/panel.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'
import { ui } from '$lib/crm/stores/ui.svelte'
import { errorText, write } from '$lib/crm/write'

const me = createQuery(() => crmQueries.me())
const today = $derived(me.data?.today ?? '')
const month = $derived(ui.calMonth || (today ? monthOf(today) : ''))
const grid = $derived(month ? monthGrid(month) : [])
const googleCalendar = createQuery(() => crmQueries.googleCalendar())
// Loading events pulls Google's changes, so coming back to the tab picks up edits made there.
const events = createQuery(() => ({
	...crmQueries.events(grid[0] ?? '', grid[41] ?? ''),
	enabled: grid.length > 0,
	refetchOnWindowFocus: Boolean(googleCalendar.data?.connected)
}))
const side = createQuery(() => crmQueries.calendarSide())

async function syncGoogleCalendar() {
	const r = await events.refetch()
	if (r.isError) toast.show(errorText(r.error), { tone: 'error' })
	else toast.show('Synced with Google Calendar')
}

async function connectGoogleCalendar() {
	const response = await write({
		call: crm.googleCalendar.connect,
		success: null,
		undoable: false
	})
	if (response) window.location.assign(response.authorization_url)
}

// Back from Google: finish sign-in as the signed-in user, and drop the one-time code from the URL.
// afterNavigate, not onMount: replaceState needs the router, which is not ready on a first load.
afterNavigate(() => {
	const back = googleReturn(window.location.hash)
	if (!back) return
	replaceState(`${window.location.pathname}${window.location.search}`, {})
	if ('error' in back) {
		toast.show('Google Calendar was not connected', { tone: 'error' })
		return
	}
	void write({
		call: () => crm.googleCalendar.complete(back.code, back.state),
		success: (s) =>
			s.email ? `Google Calendar connected (${s.email})` : 'Google Calendar connected',
		undoable: false
	})
})

async function disconnectGoogleCalendar() {
	await write({
		call: () => crm.googleCalendar.disconnect(),
		success: 'Google Calendar disconnected',
		undoable: false
	})
}

const inMonth = $derived(
	(events.data ?? []).filter(
		(e) => monthOf(e.date) <= month && monthOf(e.end_date || e.date) >= month
	)
)
const syncIssue = $derived(
	googleCalendar.data?.connected &&
		(events.data ?? []).some((event) => event.google_sync_status === 'error')
)
// A rescheduled event also leaves a struck-through entry on each slot it was moved from.
const byDay = $derived(calendarDays(events.data ?? [], grid[0] ?? '', grid[41] ?? ''))
const agendaDays = $derived([...byDay.keys()].filter((d) => monthOf(d) === month).sort())

const shift = (n: number) => (ui.calMonth = addMonths(month, n))
</script>

<svelte:head><title>Calendar · CRM</title></svelte:head>

<PageHeader
	title={month ? monthTitle(month) : 'Calendar'}
	facts={events.data
		? `${inMonth.length} event${inMonth.length === 1 ? '' : 's'} this month`
		: ''}
>
	{#snippet right()}
		<div class="flex gap-2">
			{#if googleCalendar.data?.connected}
				<span class="small muted" title={googleCalendar.data.email ?? ''}>Google connected</span>
				<button
					type="button"
					class="btn ghost sm"
					disabled={events.isFetching}
					title="Pull the latest changes from Google Calendar"
					onclick={syncGoogleCalendar}
				>
					<RefreshCw size={14} class={events.isFetching ? 'sync-spin' : ''} />
					{events.isFetching ? 'Syncing…' : 'Sync'}
				</button>
				<button type="button" class="btn ghost sm" onclick={disconnectGoogleCalendar}>Disconnect</button>
			{:else if googleCalendar.data?.configured}
				<button type="button" class="btn ghost sm" onclick={connectGoogleCalendar}>
					Connect Google Calendar
				</button>
			{:else}
				<span class="small muted" title="Set Google OAuth credentials in backend environment">Google Calendar not configured</span>
			{/if}
			<button type="button" class="btn ghost sm" aria-label="Previous month" onclick={() => shift(-1)}>
				<ArrowLeft size={14} />
			</button>
			<button type="button" class="btn ghost sm" onclick={() => (ui.calMonth = '')}>Today</button>
			<button type="button" class="btn ghost sm" aria-label="Next month" onclick={() => shift(1)}>
				<ArrowRight size={14} />
			</button>
		</div>
	{/snippet}
</PageHeader>

{#if syncIssue}
	<ErrorLine message="Some calendar events haven't synced to Google yet." onretry={() => events.refetch()} bar />
{/if}

<div class="legend" aria-label="Legend">
	{#each EVENT_KIND_ORDER as k (k)}
		<span><span class="dot" style:background={EVENT_KINDS[k].color}></span>{EVENT_KINDS[k].label}</span>
	{/each}
</div>

<div class="cal-layout">
	<div class="card">
		{#if !events.data}
			{#if events.isError}
				<ErrorLine message={errorText(events.error)} onretry={() => events.refetch()} />
			{:else}
				<Skeleton rows={6} />
			{/if}
		{:else if phone.current}
			<div class="agenda">
				{#each agendaDays as date (date)}
					<div class={['dayh', date === today && 'today']}>
						{dayLabel(date)}{date === today ? ' · today' : ''}
					</div>
					<div class="list">
						{#each byDay.get(date) ?? [] as d (d.key)}
							<EventItem event={d.event} movedFrom={d.moved ? d.time ?? 'Due' : null} />
						{/each}
					</div>
				{:else}
					<Empty text="Nothing this month.">
						<button type="button" class="btn ghost sm" onclick={() => panel.open({ kind: 'new-task' })}>＋ Add</button>
					</Empty>
				{/each}
			</div>
		{:else}
			<div class="cal" role="grid" aria-label={monthTitle(month)}>
				<div class="contents" role="row">
					{#each WEEKDAYS as w (w)}<div class="h" role="columnheader">{w}</div>{/each}
				</div>
				{#each [0, 1, 2, 3, 4, 5] as week (week)}
					<div class="contents" role="row">
						{#each grid.slice(week * 7, week * 7 + 7) as date (date)}
							{@const evs = byDay.get(date) ?? []}
							<div
								class={['c', monthOf(date) !== month && 'out', date === today && 'today']}
								role="gridcell"
							>
								<button
									type="button"
									class="addday"
									aria-label="New task on {dayLabel(date)}"
									onclick={() => panel.open({ kind: 'new-task', date })}
								></button>
								<span class="dn">{dayOfMonth(date)}</span>
								{#each evs.slice(0, 3) as d (d.key)}
									<button
										type="button"
										class={['ev', d.moved && 'moved']}
										style:--e={EVENT_KINDS[d.event.kind].color}
										title={d.moved
											? `${d.event.title} · rescheduled to ${shortDate(d.event.date)}${d.event.time ? ` ${d.event.time}` : ''}`
											: d.event.title}
										onclick={() => openEvent(d.event)}
									>
										{d.time ? `${d.time} ` : ''}{d.event.title}
									</button>
								{/each}
								{#if evs.length > 3}
									<button
										type="button"
										class="ev"
										style:--e="var(--line-2)"
										onclick={() => panel.open({ kind: 'day', date })}
									>
										+{evs.length - 3} more
									</button>
								{/if}
							</div>
						{/each}
					</div>
				{/each}
			</div>
		{/if}
	</div>

	<div class="side">
		<section class="card" aria-labelledby="overdue-h">
			<div class="ch">
				<h2 id="overdue-h">Overdue</h2>
				{#if side.data}<Chip tone="red">{side.data.overdue.length}</Chip>{/if}
			</div>
			<QueryView query={side} rows={2}>
				{#snippet children(s)}
					<div class="list">
						{#each s.overdue as o (o.text)}
							<button type="button" class="li" onclick={() => openLead(o.lead_id)}>
								<span class="dot" style:background="var(--red)"></span>
								<span><div class="t">{o.text}</div><div class="d">{o.detail}</div></span>
								<span></span>
							</button>
						{:else}
							<Empty text="Nothing overdue." />
						{/each}
					</div>
				{/snippet}
			</QueryView>
		</section>
		<section class="card" aria-labelledby="deadlines-h">
			<div class="ch"><h2 id="deadlines-h">Deadlines</h2></div>
			<QueryView query={side} rows={3}>
				{#snippet children(s)}
					<div class="list">
						{#each s.deadlines as d (d.event.id)}
							<button type="button" class="li" onclick={() => openEvent(d.event)}>
								<span class="time">{shortDate(d.event.date)}</span>
								<span><div class="t">{d.event.title}</div><div class="d">{d.event.detail}</div></span>
								<Chip chip={d.chip} />
							</button>
						{:else}
							<Empty text="No deadlines ahead." />
						{/each}
					</div>
				{/snippet}
			</QueryView>
		</section>
	</div>
</div>

<style>
	:global(.sync-spin) {
		animation: calendar-spin 0.9s linear infinite;
	}
	@keyframes calendar-spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
