<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import ArrowRight from 'lucide-svelte/icons/arrow-right'
import Check from 'lucide-svelte/icons/check'
import RefreshCw from 'lucide-svelte/icons/refresh-cw'
import { afterNavigate, replaceState } from '$app/navigation'
import { crm } from '$lib/crm/api'
import {
	calendarDays,
	calendarScope,
	eventColor,
	eventsOn,
	googleReturn,
	hasShared,
	ownerLabel,
	ownerTeam,
	showFilter,
	viewHeading,
	viewOptions
} from '$lib/crm/calendar'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import ErrorLine from '$lib/crm/components/ui/ErrorLine.svelte'
import EventItem from '$lib/crm/components/ui/EventItem.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Skeleton from '$lib/crm/components/ui/Skeleton.svelte'
import { EVENT_KIND_ORDER, EVENT_KINDS } from '$lib/crm/config'
import { openEvent } from '$lib/crm/events'
import {
	addMonths,
	dayLabel,
	dayOfMonth,
	fullDate,
	monthGrid,
	monthOf,
	monthTitle,
	shortDate,
	WEEKDAYS
} from '$lib/crm/format'
import { crmIdentity } from '$lib/crm/identity.svelte'
import { crmQueries } from '$lib/crm/queries'
import { phone } from '$lib/crm/stores/media.svelte'
import { panel } from '$lib/crm/stores/panel.svelte'
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
// Only for wording and the Show dropdown: the server already decided whose events were sent.
const assignmentScope = createQuery(() => crmQueries.assignmentScope())

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

const syncIssue = $derived(
	googleCalendar.data?.connected &&
		(events.data ?? []).some((event) => event.google_sync_status === 'error')
)
const scope = $derived(calendarScope(assignmentScope.data))
// Manager/owner view: colleagues' events are in the list, so every event says whose it is.
const shared = $derived(hasShared(events.data ?? []))
const options = $derived(viewOptions(scope, crmIdentity.userId, events.data ?? []))
const choice = $derived(options.some((o) => o.value === ui.calShow) ? ui.calShow : 'all')
const shown = $derived(showFilter(events.data ?? [], choice))
const heading = $derived(viewHeading(scope, choice))
const inMonth = $derived(
	shown.filter((e) => monthOf(e.date) <= month && monthOf(e.end_date || e.date) >= month)
)
// A rescheduled event also leaves a struck-through entry on each slot it was moved from.
const byDay = $derived(calendarDays(shown, grid[0] ?? '', grid[41] ?? ''))
const agendaDays = $derived([...byDay.keys()].filter((d) => monthOf(d) === month).sort())
const selectedDay = $derived(ui.calDay || today)
const dayEvents = $derived(selectedDay ? eventsOn(shown, selectedDay) : [])

const shift = (n: number) => (ui.calMonth = addMonths(month, n))
const goToday = () => {
	ui.calMonth = ''
	ui.calDay = ''
}
/** "You", or a colleague's name, role and team: "Aisha K · Agent · Marina Team". */
const whose = (e: (typeof shown)[number]) =>
	[ownerLabel(e), ownerTeam(scope, e)].filter(Boolean).join(' · ')
</script>

<svelte:head><title>Calendar · CRM</title></svelte:head>

<PageHeader title="Calendar" facts={heading.description}>
	{#snippet right()}
		<div class="flex gap-2">
			{#if options.length}
				<div class="cal-picker">
					<label for="cal-view">View calendar</label>
					<select
						id="cal-view"
						aria-describedby="cal-view-help"
						value={choice}
						onchange={(e) => (ui.calShow = e.currentTarget.value)}
					>
						{#each options as o (o.value)}
							<option value={o.value}>{o.label}</option>
						{/each}
					</select>
					<span id="cal-view-help">Only calendars this role can access are listed.</span>
				</div>
			{/if}
			{#if googleCalendar.data?.connected}
				<span class="small muted">
					Google connected{googleCalendar.data.email ? ` · ${googleCalendar.data.email}` : ''}
				</span>
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
		</div>
	{/snippet}
</PageHeader>

{#if syncIssue}
	<ErrorLine message="Some calendar events haven't synced to Google yet." onretry={() => events.refetch()} bar />
{/if}

<div class="cal-layout">
	<section class="card cal-card" aria-label="Calendar">
		<div class="cal-head">
			<div>
				<h2>{month ? monthTitle(month) : 'Calendar'}</h2>
				{#if events.data}
					<span class="small muted">{inMonth.length} event{inMonth.length === 1 ? '' : 's'} this month</span>
				{/if}
			</div>
			<div class="flex gap-2">
				{#if !phone.current}
					<Seg
						label="Calendar view"
						items={[
							{ id: 'month' as const, label: 'Month' },
							{ id: 'list' as const, label: 'List' }
						]}
						value={ui.calView}
						onselect={(v) => (ui.calView = v)}
					/>
				{/if}
				<button type="button" class="btn ghost sm" aria-label="Previous month" onclick={() => shift(-1)}>
					<ArrowLeft size={14} />
				</button>
				<button type="button" class="btn ghost sm" onclick={goToday}>Today</button>
				<button type="button" class="btn ghost sm" aria-label="Next month" onclick={() => shift(1)}>
					<ArrowRight size={14} />
				</button>
			</div>
		</div>

		{#if !events.data}
			{#if events.isError}
				<ErrorLine message={errorText(events.error)} onretry={() => events.refetch()} />
			{:else}
				<Skeleton rows={6} />
			{/if}
		{:else if phone.current || ui.calView === 'list'}
			<div class="agenda">
				{#each agendaDays as date (date)}
					<div class={['dayh', date === today && 'today']}>
						{dayLabel(date)}{date === today ? ' · today' : ''}
					</div>
					<div class="list">
						{#each byDay.get(date) ?? [] as d (d.key)}
							<EventItem event={d.event} movedFrom={d.moved ? d.time ?? 'Due' : null} showOwner={shared} />
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
								class={[
									'c',
									monthOf(date) !== month && 'out',
									date === today && 'today',
									date === selectedDay && 'sel'
								]}
								role="gridcell"
							>
								<button
									type="button"
									class="addday"
									aria-label="New task on {dayLabel(date)}"
									onclick={() => panel.open({ kind: 'new-task', date })}
								></button>
								<button
									type="button"
									class="dn"
									aria-label="Show {dayLabel(date)}"
									aria-pressed={date === selectedDay}
									onclick={() => (ui.calDay = date)}
								>
									{dayOfMonth(date)}
								</button>
								{#each evs.slice(0, 3) as d (d.key)}
									<button
										type="button"
										class={['ev', d.moved && 'moved', !d.event.can_edit && 'shared']}
										style:--e={eventColor(d.event)}
										title={d.moved
											? `${ownerLabel(d.event)}: ${d.event.title} · rescheduled to ${shortDate(d.event.date)}${d.event.time ? ` ${d.event.time}` : ''}`
											: `${ownerLabel(d.event)}: ${d.event.title}`}
										onclick={() => {
											ui.calDay = date
											openEvent(d.event)
										}}
									>
										{#if d.time}<span class="evtime">{d.time}</span>{/if}
										<span class="evt">{d.event.title}</span>
										{#if shared}<span class="evo">{d.event.can_edit ? 'You' : d.event.agent}</span>{/if}
									</button>
								{/each}
								{#if evs.length > 3}
									<button
										type="button"
										class="ev more"
										style:--e="var(--line-2)"
										onclick={() => (ui.calDay = date)}
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

		<div class="cal-foot">
			<div class="legend" aria-label="Event types">
				{#each EVENT_KIND_ORDER as k (k)}
					<span><span class="dot" style:background={EVENT_KINDS[k].color}></span>{EVENT_KINDS[k].label}</span>
				{/each}
			</div>
			<p class="small muted">
				Each person connects their own Google Calendar.
				{#if shared}Colleagues' events show their last synced copy; changes they make in Google appear after
					they open their own calendar.{/if}
			</p>
		</div>
	</section>

	<div class="side">
		<section class="card" aria-labelledby="day-h">
			<div class="ch">
				<h2 id="day-h">Selected day</h2>
				<span class="pill">{dayEvents.length} event{dayEvents.length === 1 ? '' : 's'}</span>
			</div>
			{#if selectedDay}<p class="day-date">{fullDate(selectedDay)}</p>{/if}
			<div class="list">
				{#each dayEvents as e (e.id)}
					<button type="button" class="li evrow" onclick={() => openEvent(e)}>
						<span class="time">{e.time ?? 'All day'}{#if e.end_time}<br />{e.end_time}{/if}</span>
						<span class="bar" style:background={eventColor(e)}></span>
						<span>
							<div class="t">{e.title}</div>
							<div class="d">
								{#if e.redacted}Private event · details hidden · {e.agent}{:else}{whose(e)}{/if}
							</div>
						</span>
						<span class="small muted">{e.can_edit ? '' : 'View only'}</span>
					</button>
				{:else}
					<Empty text="No events on this day." />
				{/each}
			</div>
		</section>

		<section class="card" aria-labelledby="access-h">
			<div class="ch">
				<h2 id="access-h">Your calendar access</h2>
				<span class="pill">{heading.pill}</span>
			</div>
			<ul class="access">
				{#each scope.rules as [title, body] (title)}
					<li>
						<span class="tick" aria-hidden="true"><Check size={13} /></span>
						<span><strong>{title}</strong>{body}</span>
					</li>
				{/each}
			</ul>
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
