<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Building from 'lucide-svelte/icons/building-2'
import User from 'lucide-svelte/icons/user'
import { untrack } from 'svelte'
import { crm } from '../../api'
import type { EventCreate, EventKind } from '../../api/types'
import { EVENT_KIND_ORDER, EVENT_KINDS } from '../../config'
import { addDays, dayLabel, monthOf } from '../../format'
import { crmQueries } from '../../queries'
import { panel } from '../../stores/panel.svelte'
import { ui } from '../../stores/ui.svelte'
import { write } from '../../write'
import GuestInput from '../ui/GuestInput.svelte'
import Panel from '../ui/Panel.svelte'
import SearchPicker from '../ui/SearchPicker.svelte'

/** With `id`, edits that event (and its Google Calendar copy) instead of adding one. */
let { date: initialDate, id }: { date?: string; id?: number } = $props()
const existing = createQuery(() => ({ ...crmQueries.event(id ?? 0), enabled: id != null }))

const me = createQuery(() => crmQueries.me())
const leads = createQuery(() => crmQueries.leads({}))
const listings = createQuery(() => crmQueries.listings('company', 'live', 100))
const googleCalendar = createQuery(() => crmQueries.googleCalendar())
const leadOptions = $derived(
	(leads.data?.items ?? []).filter((lead) => lead.id > 0 && lead.stage !== 'lost')
)
const listingOptions = $derived(
	(listings.data?.items ?? []).filter((listing) => listing.status !== 'expired')
)
const leadPicks = $derived(
	leadOptions.map((lead) => ({ id: String(lead.id), label: lead.name, meta: lead.summary.line }))
)
const listingPicks = $derived(
	listingOptions.map((listing) => ({ id: listing.id, label: listing.unit, meta: listing.area }))
)

let title = $state('')
let date = $state(untrack(() => initialDate ?? ''))
let endDate = $state(untrack(() => initialDate ?? ''))
let time = $state('10:00')
let endTime = $state('11:00')
let allDay = $state(false)
let repeat = $state<'none' | 'daily' | 'weekly' | 'monthly' | 'yearly'>('none')
let kind = $state<EventKind>('call')
let meet = $state(false)
let location = $state('')
let reminders = $state<number[]>([30])
let remindersUseDefault = $state(false)
let guests = $state<string[]>([])
let guestsCanModify = $state(false)
let guestsCanInviteOthers = $state(true)
let guestsCanSeeOtherGuests = $state(true)
let showAs = $state<'busy' | 'free'>('busy')
let visibility = $state<'default' | 'public' | 'private' | 'confidential'>('default')
let detail = $state('')
let leadId = $state('')
let listingId = $state('')
let saving = $state(false)
let loaded = $state(false)

$effect(() => {
	const e = existing.data
	if (!e || loaded) return
	title = e.title
	date = e.date
	endDate = e.end_date
	time = e.time ?? '10:00'
	endTime = e.end_time ?? '11:00'
	allDay = e.all_day
	repeat = e.repeat
	kind = e.kind
	meet = e.meet
	location = e.location
	reminders = [...e.reminders]
	remindersUseDefault = e.reminders_use_default
	guests = [...e.guests]
	guestsCanModify = e.guests_can_modify
	guestsCanInviteOthers = e.guests_can_invite_others
	guestsCanSeeOtherGuests = e.guests_can_see_other_guests
	showAs = e.show_as
	visibility = e.visibility
	detail = e.detail
	leadId = e.lead_id ? String(e.lead_id) : ''
	listingId = e.listing_id ?? ''
	loaded = true
})

const invalidEnd = $derived(
	!endDate || endDate < date || (!allDay && date === endDate && endTime <= time)
)

$effect(() => {
	if (!date && me.data) {
		date = addDays(me.data.today, 1)
		endDate = date
	}
})

async function submit(e: SubmitEvent) {
	e.preventDefault()
	saving = true
	const body: EventCreate = {
		title: title.trim(),
		date,
		time: allDay ? null : time || null,
		end_date: endDate || date,
		end_time: allDay ? null : endTime || null,
		all_day: allDay,
		repeat,
		kind,
		meet,
		location: location.trim(),
		reminders: remindersUseDefault ? [] : reminders,
		reminders_use_default: remindersUseDefault,
		guests,
		guests_can_modify: guestsCanModify,
		guests_can_invite_others: guestsCanInviteOthers,
		guests_can_see_other_guests: guestsCanSeeOtherGuests,
		show_as: showAs,
		visibility,
		detail: detail.trim(),
		lead_id: leadId ? Number(leadId) : null,
		listing_id: listingId || null
	}
	const r = await write({
		call: () => (id != null ? crm.events.update(id, body) : crm.events.create(body)),
		success: id != null ? `Saved · ${body.title}` : `Added ${dayLabel(date)}`
	})
	saving = false
	if (r) {
		ui.weekDay = date
		ui.calMonth = monthOf(date)
		if (id != null) panel.open({ kind: 'event', id })
		else panel.close()
	}
}
</script>

<Panel kicker={id != null ? 'Edit event' : 'New event'} title={id != null ? (existing.data?.title ?? 'Edit event') : 'Add to calendar'}>
	{#snippet footer()}
		<div class="calendar-actions">
			<span class="small muted">{googleCalendar.data?.connected ? (id != null ? 'Changes sync to Google Calendar' : 'Will sync to Google Calendar') : 'Saved to CRM calendar'}</span>
			<div class="calendar-buttons">
				<button type="button" class="btn ghost" onclick={() => (id != null ? panel.open({ kind: 'event', id }) : panel.close())}>Cancel</button>
				<button type="submit" form="new-calendar-event" class="btn" disabled={saving || !date || invalidEnd || (id != null && !loaded)}>
					{saving ? 'Saving…' : id != null ? 'Save changes' : 'Save event'}
				</button>
			</div>
		</div>
	{/snippet}
	<form id="new-calendar-event" class="form calendar-form" onsubmit={submit}>
		<input id="nt-title" class="title-input" required aria-label="Title" placeholder="Add title" bind:value={title} />
		<div class="cal-grid">
			<div class="cal-col">
				<section class="cal-section" aria-labelledby="nt-when">
					<h3 id="nt-when">Date and time</h3>
					<div class="frow">
						<div class="fld">
							<label for="nt-date">Start date</label>
							<input
								id="nt-date"
								type="date"
								required
								bind:value={date}
								onchange={() => {
									if (!endDate || endDate < date) endDate = date
								}}
							/>
						</div>
						<div class="fld">
							<label for="nt-end-date">End date</label>
							<input id="nt-end-date" type="date" required min={date} bind:value={endDate} />
						</div>
					</div>
					{#if !allDay}
						<div class="frow">
							<div class="fld">
								<label for="nt-time">Start time</label>
								<input id="nt-time" type="time" required bind:value={time} />
							</div>
							<div class="fld">
								<label for="nt-end-time">End time</label>
								<input id="nt-end-time" type="time" required bind:value={endTime} />
							</div>
						</div>
					{/if}
					<div class="frow when-row">
						<label class="small inline-check"><input type="checkbox" bind:checked={allDay} /> All day</label>
						<select aria-label="Repeat" bind:value={repeat}>
							<option value="none">Does not repeat</option>
							<option value="daily">Daily</option>
							<option value="weekly">Weekly</option>
							<option value="monthly">Monthly</option>
							<option value="yearly">Yearly</option>
						</select>
					</div>
					{#if !allDay}<div class="small muted">Time zone · Asia/Dubai</div>{/if}
				</section>

				<section class="cal-section" aria-labelledby="nt-details">
					<h3 id="nt-details">Meeting details</h3>
					<div class="frow">
						<div class="fld">
							<label for="nt-kind">Event type</label>
							<select id="nt-kind" bind:value={kind}>
								{#each EVENT_KIND_ORDER as k (k)}<option value={k}>{EVENT_KINDS[k].label}</option>{/each}
							</select>
						</div>
						<div class="fld">
							<label for="nt-location">Location</label>
							<input id="nt-location" placeholder="Add location" bind:value={location} />
						</div>
					</div>
					<label class={['meet-toggle', meet && 'on', !googleCalendar.data?.connected && 'off']}>
						<input type="checkbox" bind:checked={meet} disabled={!googleCalendar.data?.connected} />
						<span>
							<strong>Google Meet video conferencing</strong>
							<span class="small muted">
								{googleCalendar.data?.connected ? 'A Meet link is added to the invitation' : 'Connect Google Calendar to create Meet links'}
							</span>
						</span>
					</label>
					<div class="fld">
						<label for="nt-guests">Guests{guests.length ? ` · ${guests.length}` : ''}</label>
						<GuestInput id="nt-guests" bind:guests />
						<div class="small muted">
							{googleCalendar.data?.connected ? 'Google Calendar emails invitations to guests.' : 'Connect Google Calendar to email invitations.'}
						</div>
					</div>
					<div class="fld">
						<label for="nt-detail">Description</label>
						<textarea id="nt-detail" rows="4" maxlength="2000" placeholder="Add description" bind:value={detail}></textarea>
					</div>
				</section>
			</div>

			<div class="cal-col side">
				<section class="cal-section" aria-labelledby="nt-links">
					<h3 id="nt-links">Linked records</h3>
					<SearchPicker
						block
						label="Lead / client"
						icon={User}
						options={leadPicks}
						value={leadId}
						onselect={(v) => (leadId = v)}
						allLabel="No linked lead"
						noun="leads"
					/>
					<SearchPicker
						block
						label="Property / listing"
						icon={Building}
						options={listingPicks}
						value={listingId}
						onselect={(v) => (listingId = v)}
						allLabel="No linked listing"
						noun="listings"
					/>
				</section>

				<section class="cal-section" aria-labelledby="nt-notify">
					<h3 id="nt-notify">Notifications</h3>
					<label class="small inline-check"><input type="checkbox" bind:checked={remindersUseDefault} /> Use Google Calendar default reminders</label>
					{#if !remindersUseDefault}
						{#each reminders as reminder, i (i)}
							<div class="reminder">
								<select aria-label="Notification {i + 1}" bind:value={reminders[i]}>
									<option value={0}>At event time</option>
									<option value={5}>5 minutes before</option>
									<option value={10}>10 minutes before</option>
									<option value={15}>15 minutes before</option>
									<option value={30}>30 minutes before</option>
									<option value={60}>1 hour before</option>
									<option value={1440}>1 day before</option>
								</select>
								<button
									type="button"
									class="btn ghost sm"
									aria-label="Remove notification {i + 1}"
									onclick={() => (reminders = reminders.filter((_, index) => index !== i))}
								>Remove</button>
							</div>
						{/each}
						{#if reminders.length < 5}
							<button type="button" class="btn ghost sm add" onclick={() => (reminders = [...reminders, 30])}>＋ Add notification</button>
						{/if}
					{/if}
				</section>

				<section class="cal-section" aria-labelledby="nt-perms">
					<h3 id="nt-perms">Guest permissions</h3>
					<label class="small inline-check"><input type="checkbox" bind:checked={guestsCanModify} /> Modify event</label>
					<label class="small inline-check"><input type="checkbox" bind:checked={guestsCanInviteOthers} /> Invite others</label>
					<label class="small inline-check"><input type="checkbox" bind:checked={guestsCanSeeOtherGuests} /> See guest list</label>
				</section>

				<section class="cal-section" aria-labelledby="nt-cal">
					<h3 id="nt-cal">Calendar</h3>
					<div class="small">{googleCalendar.data?.connected ? `Google Calendar · ${googleCalendar.data.email}` : 'CRM calendar (connect Google Calendar to sync)'}</div>
					<div class="frow">
						<div class="fld">
							<label for="nt-show-as">Show as</label>
							<select id="nt-show-as" bind:value={showAs}><option value="busy">Busy</option><option value="free">Free</option></select>
						</div>
						<div class="fld">
							<label for="nt-visibility">Visibility</label>
							<select id="nt-visibility" bind:value={visibility}>
								<option value="default">Default</option><option value="public">Public</option><option value="private">Private</option><option value="confidential">Confidential</option>
							</select>
						</div>
					</div>
				</section>
			</div>
		</div>
	</form>
</Panel>

<style>
	.calendar-form { gap: 1rem; }
	.title-input {
		width: 100%;
		min-height: 52px;
		padding: 0 0.2rem;
		border: 0;
		border-bottom: 2px solid var(--line);
		border-radius: 0;
		background: transparent;
		font-size: 1.35rem;
		font-weight: 600;
		box-shadow: none;
	}
	.title-input:focus { outline: none; border-bottom-color: var(--accent); }
	.cal-grid {
		display: grid;
		grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr);
		gap: 1.25rem;
		align-items: start;
	}
	.cal-col { display: grid; gap: 1rem; min-width: 0; }
	.cal-col.side {
		padding: 0.25rem 1rem;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--card-2);
	}
	.cal-section { display: grid; gap: 0.7rem; padding: 0.75rem 0; }
	.cal-section + .cal-section { border-top: 1px solid var(--line); }
	.cal-section h3 {
		margin: 0;
		font-size: 0.78rem;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text2);
	}
	.when-row { align-items: center; }
	.inline-check { display: flex; align-items: center; gap: 0.5rem; cursor: pointer; }
	.inline-check :global(input) { width: auto; flex: none; margin: 0; }
	.meet-toggle {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.7rem 0.85rem;
		border: 1px solid var(--line);
		border-radius: 10px;
		cursor: pointer;
	}
	.meet-toggle.on { border-color: var(--accent); background: var(--sel); }
	.meet-toggle.off { cursor: not-allowed; opacity: 0.7; }
	.meet-toggle input { width: auto; flex: none; margin: 0; }
	.meet-toggle > span { display: grid; gap: 0.1rem; }
	.meet-toggle strong { font-size: 0.88rem; font-weight: 600; }
	.reminder { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.5rem; align-items: center; }
	.add { justify-self: start; }
	.calendar-actions { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; }
	.calendar-buttons { display: flex; gap: 0.5rem; }
	@media (max-width: 820px) {
		.cal-grid { grid-template-columns: 1fr; }
	}
	@media (max-width: 520px) { .calendar-actions .muted { display: none; } }
</style>
