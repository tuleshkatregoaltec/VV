<script lang="ts">
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import ArrowRight from 'lucide-svelte/icons/arrow-right'
import CalendarDays from 'lucide-svelte/icons/calendar-days'
import Check from 'lucide-svelte/icons/check'
import CheckCheck from 'lucide-svelte/icons/check-check'
import ChevronRight from 'lucide-svelte/icons/chevron-right'
import CircleCheck from 'lucide-svelte/icons/circle-check'
import Clock from 'lucide-svelte/icons/clock-3'
import House from 'lucide-svelte/icons/house'
import Inbox from 'lucide-svelte/icons/inbox'
import Link from 'lucide-svelte/icons/link-2'
import Lock from 'lucide-svelte/icons/lock-keyhole'
import Mail from 'lucide-svelte/icons/mail'
import Maximize from 'lucide-svelte/icons/maximize-2'
import MessageCircle from 'lucide-svelte/icons/message-circle'
import Moon from 'lucide-svelte/icons/moon'
import RotateCcw from 'lucide-svelte/icons/rotate-ccw'
import ShieldCheck from 'lucide-svelte/icons/shield-check'
import Sparkles from 'lucide-svelte/icons/sparkles'
import Sun from 'lucide-svelte/icons/sun'
import UserRound from 'lucide-svelte/icons/user-round'
import X from 'lucide-svelte/icons/x'
import '$lib/crm/crm.css'
import { colorTheme } from '$lib/stores/preferences.svelte'

// This public preview deliberately has no API imports, provider SDKs or persisted records.
// Every interaction is local sample state, including confirmations and provider receipts.
const steps = ['Enquiry received', 'Lead approved', 'Find a viewing', 'Review & approve', 'All set']
let progress = $state(0)
let view = $state(0)
let channel = $state<'agent' | 'customer'>('agent')
let mailProvider = $state<'Gmail' | 'Outlook'>('Gmail')
let calendarProvider = $state<'Google Calendar' | 'Microsoft Calendar'>('Google Calendar')
let connected = $state({ mail: true, calendar: true, whatsapp: true })
let activeConnection = $state<'mail' | 'calendar' | 'whatsapp'>('mail')
let connectionDialog: HTMLDialogElement
let slot = $state('16:30')
let invite = $state(true)
let reply = $state(true)
let replyText = $state(
	'Hi Maya, your Marina Gate viewing is arranged for Tuesday at 16:30. I’ll meet you in the lobby. — Sara'
)
let approvedReply = $state('')
let approvedInvite = $state(false)
let approvedMessage = $state(false)
let presenter = $state(false)
let announcement = $state('')
const dark = $derived(colorTheme.resolved === 'dark')
const canProceed = $derived(connected.mail && connected.calendar && connected.whatsapp)
const connectionTitle = $derived(
	activeConnection === 'mail' ? 'Email' : activeConnection === 'calendar' ? 'Calendar' : 'WhatsApp'
)

function advance(next: number) {
	if (!canProceed) return
	progress = Math.max(progress, next)
	view = next
	announcement = steps[next]
}
function selectSlot(value: string) {
	if (value !== slot && progress >= 3) {
		progress = view = 2
		approvedReply = ''
		approvedInvite = approvedMessage = false
		announcement = 'Viewing time changed. Review and approve the new details.'
	}
	slot = value
	replyText = `Hi Maya, your Marina Gate viewing is arranged for Tuesday at ${value}. I’ll meet you in the lobby. — Sara`
}
function approve() {
	if (!canProceed || progress !== 3 || (reply && !replyText.trim())) return
	approvedReply = replyText
	approvedInvite = invite
	approvedMessage = reply
	advance(4)
}
function restart() {
	progress = view = 0
	channel = 'agent'
	slot = '16:30'
	invite = reply = true
	connected = { mail: true, calendar: true, whatsapp: true }
	approvedReply = ''
	approvedInvite = approvedMessage = false
	replyText =
		'Hi Maya, your Marina Gate viewing is arranged for Tuesday at 16:30. I’ll meet you in the lobby. — Sara'
	announcement = 'Demo restarted. Sample enquiry ready.'
}
function manage(connection: typeof activeConnection) {
	activeConnection = connection
	connectionDialog.showModal()
}
function toggleConnection() {
	connected = { ...connected, [activeConnection]: !connected[activeConnection] }
	announcement = `${connectionTitle} demo ${connected[activeConnection] ? 'connected' : 'disconnected'}`
	connectionDialog.close()
}
</script>

<div class:presenter class="crm-root demo-page">
	<header class="demo-nav">
		<a class="brand" href="/" aria-label="Vitevue home"><img class="brand-mark" src="/landing/logos/vitevue-mark-navy.svg" alt="" width="33" height="33" />vitevue<span class="brand-divider"></span><span class="enterprise">Enterprise</span></a>
		<div class="nav-actions">
			<span class="demo-label"><span></span> Demo · Sample data</span>
			<button class="quiet presenter-button" onclick={() => (presenter = !presenter)} aria-pressed={presenter}><Maximize size={15} /><span>{presenter ? 'Exit presentation' : 'Present'}</span></button>
			<button class="quiet icon-only" onclick={() => colorTheme.toggle()} aria-label={dark ? 'Switch to light' : 'Switch to dark'}>{#if dark}<Sun size={18} />{:else}<Moon size={18} />{/if}</button>
		</div>
	</header>

	<main class="demo-main">
		<section class="intro" aria-label="Connected assistant overview">
			<div><div class="eyebrow"><span class="small-line"></span> THE CONNECTED WORKSPACE</div><h1>Less coordination.<br /><span>More conversations.</span></h1><p>Your enquiries, calendar and WhatsApp, working together.<br class="desktop-break" /> One assistant. Your team stays in control.</p></div>
			<div class="intro-note"><div class="intro-icon"><Sparkles size={21} /></div><strong>A viewing, from first hello.</strong><p>Follow Sara’s day at Harbor Estates.<br />A new enquiry becomes a lead, then a viewing.</p><span><Clock size={13} /> A two-minute walkthrough</span></div>
		</section>

		<section class="connections" aria-label="Demo connections">
			{#each [{ id: 'mail' as const, icon: Mail, title: mailProvider, detail: 'sara@harborestates.example', caption: 'Portal enquiries → private lead candidates' }, { id: 'calendar' as const, icon: CalendarDays, title: calendarProvider, detail: 'Sara’s work calendar · Dubai', caption: 'Availability → conflict-free viewing proposals' }, { id: 'whatsapp' as const, icon: MessageCircle, title: 'WhatsApp Business', detail: 'Assistant number + customer inbox', caption: 'Agent requests → approved customer replies' }] as connection}
				<article class="connection-card">
					<div class="connection-top"><span class="connection-icon" class:whatsapp={connection.id === 'whatsapp'}><connection.icon size={20} /></span><span class="connection-status" class:offline={!connected[connection.id]}>{#if connected[connection.id]}<Check size={12} /> Demo connected{:else}Disconnected{/if}</span></div>
					<div class="connection-title"><h2>{connection.title}</h2><button class="text-button" onclick={() => manage(connection.id)} aria-label={`Manage ${connection.id} demo connection`}>{connected[connection.id] ? 'Manage' : 'Connect'}<ChevronRight size={13} /></button></div>
					<p class="account">{connection.detail}</p><p class="connection-caption">{connection.caption}</p>
				</article>
			{/each}
		</section>

		<section class="walkthrough" aria-label="Enquiry to viewing demo">
			<div class="walkthrough-heading"><div><span class="eyebrow">YOUR ASSISTANT AT WORK</span><h2>One enquiry. One connected workflow.</h2></div><button class="quiet" onclick={restart}><RotateCcw size={14} /> Restart demo</button></div>
			<nav class="steps" aria-label="Workflow steps">
				{#each steps as step, index}<button class:current={view === index} class:complete={progress > index} disabled={index > progress} onclick={() => (view = index)} aria-current={view === index ? 'step' : undefined}><span class="step-number">{#if progress > index}<Check size={13} />{:else}{index + 1}{/if}</span><span>{step}</span></button>{/each}
			</nav>
			{#if !canProceed}<div class="reconnect" role="status"><Link size={16} /> Reconnect the demo accounts to continue. Use Manage on the connection cards above.</div>{/if}
			<div class="workspace">
				<section class="work-panel" aria-label="Sample workspace">
					<div class="panel-bar"><span><span class="avatar small">SA</span> Sara Ali <span class="muted">/ Harbor Estates</span></span><span class="sample-pill">SAMPLE WORKSPACE</span></div>
					{#if view === 0}
						<div class="scene email-scene">
							<div class="scene-heading"><span class="scene-icon"><Inbox size={20} /></span><div><span class="eyebrow">NEW PORTAL ENQUIRY</span><h3>A new home. A new conversation.</h3></div><span class="timestamp">09:41</span></div>
							<div class="email"><div class="email-from"><span class="avatar customer">MH</span><div><strong>Maya Hassan</strong><span>via Property Finder · to Sara</span></div><span class="new-pill">New</span></div><h4>Viewing enquiry · Marina Gate, 2 bedrooms</h4><p>Hi Sara, I’m interested in the two-bedroom apartment at Marina Gate. My budget is around AED 2.8 million. Could we arrange a viewing on Tuesday afternoon?</p><p>Thanks,<br />Maya</p><span class="email-meta"><Mail size={13} /> maya.hassan@example.com</span></div>
							<div class="extraction"><div><Sparkles size={15} /><strong>A lead candidate, ready for your review</strong></div><p>The assistant has picked out the enquiry details. Sara approves before anything enters her CRM.</p><div class="fact-grid"><span>Interested in<strong>2-bedroom apartment</strong></span><span>Location<strong>Marina Gate · Dubai Marina</strong></span><span>Budget<strong>AED 2,800,000</strong></span><span>Preferred time<strong>Tuesday afternoon</strong></span></div></div>
							<div class="scene-footer"><span><Lock size={13} /> Private to Sara</span><button class="primary" disabled={!canProceed} onclick={() => advance(1)}>{progress > 0 ? 'View approved lead' : 'Approve lead'}<ArrowRight size={15} /></button></div>
						</div>
					{:else if view === 1}
						<div class="scene">
							<div class="scene-heading"><span class="scene-icon success"><UserRound size={20} /></span><div><span class="eyebrow">PERSONAL CRM</span><h3>A clear brief, without the retyping.</h3></div></div>
							<div class="lead-card"><div class="lead-identity"><span class="avatar large customer">MH</span><div><h4>Maya Hassan</h4><span>Buyer · Assigned to Sara Ali</span></div><span class="new-pill">New lead</span></div><div class="property-visual"><House size={44} strokeWidth={1} /><div><span>MARINA GATE</span><strong>Dubai Marina</strong><p>2 bedrooms · Apartment · Up to AED 2.8m</p></div></div><dl class="lead-details"><div><dt>Source</dt><dd>Property Finder enquiry</dd></div><div><dt>Next step</dt><dd>Arrange a viewing</dd></div><div><dt>Contact</dt><dd>maya.hassan@example.com</dd></div><div><dt>Owner</dt><dd>Sara Ali · Personal workspace</dd></div></dl><div class="activity"><CircleCheck size={16} /><div><strong>Lead approved by Sara</strong><span>Original enquiry linked as evidence · Demo activity</span></div></div></div>
							<div class="next-request"><MessageCircle size={18} /><p>Sara can now ask her assistant from WhatsApp.<br /><strong>“Find Maya a viewing on Tuesday after 3pm.”</strong></p></div>
							<div class="scene-footer"><span>Every next step keeps the same context.</span><button class="primary" disabled={!canProceed} onclick={() => { channel = 'agent'; advance(2) }}>Ask on WhatsApp<ArrowRight size={15} /></button></div>
						</div>
					{:else if view === 2}
						<div class="scene">
							<div class="scene-heading"><span class="scene-icon"><CalendarDays size={20} /></span><div><span class="eyebrow">AVAILABILITY CHECKED</span><h3>A viewing that fits Sara’s day.</h3></div></div>
							<div class="calendar"><div class="calendar-head"><div><strong>Tuesday, 3 November</strong><span>Demo week · 2026 · Dubai (UTC+4)</span></div><span class="calendar-provider">{calendarProvider}</span></div><div class="calendar-row"><time>14:00</time><div class="calendar-event blue-event"><strong>Team catch-up</strong><span>14:00–14:30 · Work calendar</span></div></div><div class="calendar-row"><time>15:00</time><div class="calendar-event busy-event"><strong>Client meeting</strong><span>15:00–16:00 · Already booked</span><span class="conflict-label">Conflict avoided</span></div></div><div class="calendar-row"><time>{slot}</time><div class="calendar-event proposed-event"><strong>Marina Gate viewing · Maya</strong><span>{slot}–{slot === '16:30' ? '17:00' : '18:00'} · Proposed, awaiting approval</span></div></div></div>
							<fieldset class="slot-picker"><legend>Choose a viewing slot</legend><button class="slot busy" disabled>15:00 <span>Busy</span></button>{#each ['16:30', '17:30'] as time}<button class="slot" class:selected={slot === time} aria-pressed={slot === time} onclick={() => selectSlot(time)}>{time}<span>{slot === time ? 'Selected' : 'Available'}</span>{#if slot === time}<Check size={14} />{/if}</button>{/each}</fieldset>
							<p class="small-note"><ShieldCheck size={14} /> Availability is checked again before a real booking.</p>
							<div class="scene-footer"><button class="text-button" onclick={() => (view = 1)}><ArrowLeft size={14} /> Lead details</button><button class="primary" disabled={!canProceed} onclick={() => advance(3)}>Review booking<ArrowRight size={15} /></button></div>
						</div>
					{:else if view === 3}
						<div class="scene">
							<div class="scene-heading"><span class="scene-icon"><ShieldCheck size={20} /></span><div><span class="eyebrow">YOUR APPROVAL, YOUR CONTROL</span><h3>Review the details. Give the go-ahead.</h3></div></div>
							<div class="approval-summary"><div class="approval-date"><span>NOV</span><strong>03</strong><span>TUE</span></div><div><h4>Marina Gate viewing with Maya</h4><p>Tuesday · {slot}–{slot === '16:30' ? '17:00' : '18:00'} · Dubai (UTC+4)</p><p>Marina Gate lobby · Sara’s work calendar</p></div></div>
							<fieldset class="approval-options" disabled={progress === 4}><legend>Include with this booking</legend><label><input type="checkbox" bind:checked={invite} /><CalendarDays size={16} /><span><strong>Send a calendar invitation</strong><small>maya.hassan@example.com · From Sara’s calendar</small></span></label><label><input type="checkbox" bind:checked={reply} /><MessageCircle size={16} /><span><strong>Send this WhatsApp reply</strong><small>To Maya · From Sara’s connected business number</small></span></label></fieldset>
							{#if reply}<label class="reply-label" for="demo-reply">Message for Maya</label><textarea id="demo-reply" rows="3" maxlength="1000" bind:value={replyText} disabled={progress === 4}></textarea>{/if}
							<p class="approval-note"><Lock size={14} /> The assistant prepares. Sara approves the exact booking and message.</p>
							<div class="scene-footer"><button class="text-button" onclick={() => (view = 2)}><ArrowLeft size={14} /> Change time</button>{#if progress === 4}<button class="primary" onclick={() => (view = 4)}>View demo result<ArrowRight size={15} /></button>{:else}<button class="primary" disabled={!canProceed || (reply && !replyText.trim())} onclick={approve}>Approve in demo<Check size={15} /></button>{/if}</div>
						</div>
					{:else}
						<div class="scene completed-scene"><span class="completion-icon"><CheckCheck size={31} /></span><span class="eyebrow">DEMO WORKFLOW COMPLETE</span><h3>From an enquiry to a viewing.<br />With Sara in control.</h3><p>Maya has a next step. Sara has her time back.<br />Every action belongs to the same conversation.</p><div class="completion-receipts"><div><CircleCheck size={18} /><span><strong>Viewing added to the demo calendar</strong><small>3 November · {slot} · Marina Gate</small></span><span class="receipt-pill">Demo receipt</span></div>{#if approvedInvite}<div><Mail size={18} /><span><strong>Calendar invitation previewed</strong><small>maya.hassan@example.com</small></span><span class="receipt-pill">Simulated</span></div>{/if}{#if approvedMessage}<div><MessageCircle size={18} /><span><strong>WhatsApp reply previewed</strong><small>{approvedReply}</small></span><span class="receipt-pill">Simulated</span></div>{/if}</div><p class="small-note">Sample data only. No messages sent or real events created.</p><button class="primary" onclick={restart}><RotateCcw size={15} /> Run the story again</button></div>
					{/if}
				</section>

				<aside class="assistant-panel" aria-label="Demo conversations">
					<div class="assistant-heading"><span class="assistant-symbol"><Sparkles size={18} /></span><div><h3>Vitevue assistant</h3><span>The same conversation, wherever you work</span></div></div>
					<div class="channel-tabs" role="tablist" aria-label="Conversation channel"><button role="tab" aria-selected={channel === 'agent'} class:active={channel === 'agent'} onclick={() => (channel = 'agent')}>Sara’s assistant<Lock size={11} /></button><button role="tab" aria-selected={channel === 'customer'} class:active={channel === 'customer'} onclick={() => (channel = 'customer')}>Customer inbox</button></div>
					{#if channel === 'agent'}
						<div class="conversation" role="tabpanel" aria-label="Sara’s private assistant conversation"><span class="conversation-date">TUESDAY · DEMO CONVERSATION</span><div class="message assistant-message"><span class="message-author">Vitevue</span><p>A new enquiry from Maya is ready. She’s looking for a two-bedroom apartment at Marina Gate, around AED 2.8m.</p><span class="message-time">09:41</span></div>{#if progress >= 2}<div class="message user-message"><p>Lead approved. Find Maya a viewing on Tuesday after 3pm.</p><span class="message-time">Sara · WhatsApp <CheckCheck size={12} /></span></div><div class="message assistant-message"><span class="message-author">Vitevue</span><p>You have a meeting at 15:00. There’s room at 16:30 or 17:30, with time to get to Marina Gate.</p><div class="evidence-tag"><CalendarDays size={12} /> Sara’s work calendar</div></div>{/if}{#if progress >= 3}<div class="message assistant-message"><span class="message-author">Vitevue</span><p>I’ve prepared the {slot} viewing and a reply for Maya. Review the details in Vitevue to approve.</p><span class="approval-chip"><ShieldCheck size={12} /> Awaiting application approval</span></div>{/if}{#if progress >= 4}<div class="message assistant-message final-message"><span class="message-author">Vitevue · Demo result</span><p>The sample viewing is ready for Tuesday at {slot}.{approvedMessage ? ' Your approved reply appears in the customer inbox preview.' : ''}</p><span class="message-time">Simulated confirmation <CheckCheck size={12} /></span></div>{/if}</div>
					{:else}
						<div class="conversation" role="tabpanel" aria-label="Customer WhatsApp inbox"><div class="customer-thread-heading"><span class="avatar customer">MH</span><div><strong>Maya Hassan</strong><span>Customer conversation · Sara’s business number</span></div></div><div class="message assistant-message"><span class="message-author">Maya</span><p>Tuesday afternoon works for me. Is there parking at the building?</p><span class="message-time">Customer message · 09:44</span></div>{#if progress >= 4 && approvedMessage}<div class="message user-message"><span class="message-author">Sara · Approved reply preview</span><p>{approvedReply}</p><span class="message-time">Demo · Not sent <CheckCheck size={12} /></span></div>{:else}<div class="customer-empty"><MessageCircle size={24} /><p>Customer messages inform the next step.<br />Replies appear here after Sara’s approval.</p></div>{/if}<p class="customer-boundary"><ShieldCheck size={13} /> Customer messages stay separate from Sara’s private assistant.</p></div>
					{/if}
					<div class="assistant-bottom"><ShieldCheck size={15} /><span>Private context. Explicit approvals.<br /><strong>Always your team’s decision.</strong></span></div>
				</aside>
			</div>
		</section>
		<footer class="demo-footer"><span><ShieldCheck size={14} /> Designed around your agents, their permissions and your customer relationships.</span><span>Interactive preview · Provider connections are simulated</span></footer>
	</main>
	<p class="sr-only" role="status" aria-live="polite">{announcement}</p>
	<dialog bind:this={connectionDialog} aria-labelledby="connection-title" class="connection-dialog">
		<div class="dialog-heading"><span class="scene-icon"><Link size={20} /></span><button class="quiet icon-only" onclick={() => connectionDialog.close()} aria-label="Close connection preview"><X size={19} /></button></div>
		<span class="eyebrow">CONNECTION PREVIEW</span><h2 id="connection-title">{connectionTitle}, on your terms.</h2><p>Explore how Sara connects her accounts. This demo uses sample accounts and never asks for credentials.</p>
		{#if activeConnection === 'mail'}<fieldset class="provider-choice"><legend>Choose your email provider</legend>{#each ['Gmail', 'Outlook'] as provider}<button class:selected={mailProvider === provider} aria-pressed={mailProvider === provider} onclick={() => (mailProvider = provider as typeof mailProvider)}><Mail size={17} />{provider}{#if mailProvider === provider}<Check size={15} />{/if}</button>{/each}</fieldset><div class="permission"><Check size={15} /><span>Read enquiries from selected sources and folders</span></div><div class="permission"><Lock size={15} /><span>Sending replies requires separate permission and approval</span></div>
		{:else if activeConnection === 'calendar'}<fieldset class="provider-choice"><legend>Choose your calendar provider</legend>{#each ['Google Calendar', 'Microsoft Calendar'] as provider}<button class:selected={calendarProvider === provider} aria-pressed={calendarProvider === provider} onclick={() => (calendarProvider = provider as typeof calendarProvider)}><CalendarDays size={17} />{provider}{#if calendarProvider === provider}<Check size={15} />{/if}</button>{/each}</fieldset><div class="permission"><Check size={15} /><span>Check your selected calendars for conflicts</span></div><div class="permission"><ShieldCheck size={15} /><span>Review bookings and invitations before they’re created</span></div>
		{:else}<div class="whatsapp-modes"><div><MessageCircle size={19} /><strong>Message your assistant</strong><p>Agents use a company assistant number to request work on their own records.</p></div><div><Inbox size={19} /><strong>Keep customer conversations connected</strong><p>Customer messages arrive through the agent’s business number, in a separate inbox.</p></div></div><div class="permission"><ShieldCheck size={15} /><span>Customer messages never approve actions</span></div>{/if}
		<div class="dialog-actions"><button class="quiet" onclick={toggleConnection}>{connected[activeConnection] ? 'Disconnect demo account' : 'Connect sample account'}</button><button class="primary" onclick={() => connectionDialog.close()}>Done<Check size={15} /></button></div>
	</dialog>
</div>

<style>
.demo-page { min-height: 100vh; background: var(--page); color: var(--text); font-family: var(--font-sans); font-size: 14px; line-height: 1.5; }
:global(:root[data-theme="dark"]) .demo-page {
    --page: var(--color-bg-app);
    --card: var(--color-bg-card);
    --sunk: var(--color-bg-panel);
    --text: var(--color-fg-1);
    --text2: var(--color-fg-3);
    --text3: var(--color-fg-4);
    --sep: var(--color-border);
    --sep-strong: var(--color-border-strong);
    --accent: #9ac5ff;
    --on-accent: #0b1b2b;
    --blue: #a8ceff;
    --blue-bg: #1b2e45;
    --green: #90d3a8;
    --green-bg: #15372c;
    --amber: #e9be7b;
    --amber-bg: #33291c;
}
.demo-nav { height: 76px; display: flex; align-items: center; justify-content: space-between; padding: 0 4.5%; border-bottom: 1px solid var(--sep); background: var(--card); gap: 16px; }
.brand { display: flex; align-items: center; gap: 10px; font-size: 25px; font-weight: 750; letter-spacing: -1px; color: var(--text); text-decoration: none; }
.brand-mark { display: grid; place-items: center; width: 33px; height: 33px; border-radius: 9px; color: white; background: #15374a; }
.brand-divider { height: 20px; width: 1px; background: var(--sep); margin: 0 8px; }
.enterprise { font-size: 14px; font-weight: 500; color: var(--text2); letter-spacing: 0; }
.nav-actions { display: flex; align-items: center; gap: 12px; }
.demo-label { display: flex; align-items: center; gap: 7px; background: var(--amber-bg); color: var(--amber); border: 1px solid color-mix(in srgb, var(--amber) 16%, transparent); border-radius: 5px; padding: 5px 9px; font-size: 13px; font-weight: 600; white-space: nowrap; }
.demo-label > span { width: 5px; height: 5px; background: currentColor; border-radius: 50%; }
.demo-main { max-width: 1440px; margin: auto; padding: 42px 4.5% 24px; }
.intro { display: flex; align-items: center; justify-content: space-between; margin-bottom: 30px; gap: 30px; }
.eyebrow { font-size: 11px; font-weight: 650; letter-spacing: 1.7px; color: var(--text2); display: flex; align-items: center; gap: 8px; }
.small-line { width: 23px; height: 2px; background: var(--accent); }
h1 { margin: 14px 0 13px; font-size: clamp(30px, 3.2vw, 47px); line-height: 1.13; font-weight: 550; letter-spacing: -1.8px; }
h1 > span { color: var(--text2); }
.intro p { color: var(--text2); line-height: 1.7; font-size: 14px; }
.intro-note { border-left: 1px solid var(--sep-strong); padding: 2px 0 2px 26px; min-width: 260px; }
.intro-note .intro-icon { color: var(--accent); margin-bottom: 10px; }
.intro-note strong { font-size: 14px; font-weight: 600; }
.intro-note p { margin: 5px 0 12px; }
.intro-note > span { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text3); }
.connections { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 13px; margin-bottom: 35px; }
.connection-card { min-width: 0; padding: 17px 19px; background: var(--card); border: 1px solid var(--sep); border-radius: 9px; }
.connection-top, .connection-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.connection-icon, .scene-icon { width: 36px; height: 36px; background: var(--blue-bg); color: var(--blue); border-radius: 8px; display: inline-grid; place-items: center; flex-shrink: 0; }
.connection-icon.whatsapp, .scene-icon.success { color: var(--green); background: var(--green-bg); }
.connection-status { display: flex; align-items: center; gap: 4px; color: var(--green); font-size: 11px; font-weight: 550; }
.connection-status.offline { color: var(--text2); }
.connection-title { margin-top: 13px; }
.connection-title h2 { margin: 0; font-size: 14px; font-weight: 600; letter-spacing: -.3px; }
.account { margin: 4px 0 13px; font-size: 12px; color: var(--text2); overflow-wrap: anywhere; }
.connection-caption { font-size: 12px; color: var(--text3); margin: 0; padding-top: 12px; border-top: 1px solid var(--sep); }
button { cursor: pointer; font: inherit; transition: background 150ms, border-color 150ms, color 150ms; }
button:disabled { cursor: not-allowed; opacity: .5; }
button:focus-visible, a:focus-visible, textarea:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; }
.quiet, .text-button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; background: transparent; border: 0; padding: 6px 8px; border-radius: 5px; font-size: 12px; color: var(--text2); }
.quiet:hover, .text-button:hover { background: var(--hover); color: var(--text); }
.text-button { color: var(--accent); padding: 4px 0; }
.icon-only { min-width: 34px; min-height: 34px; }
.primary { display: inline-flex; align-items: center; justify-content: center; gap: 11px; padding: 10px 15px; background: var(--accent); color: var(--on-accent); border: 1px solid var(--accent); border-radius: 6px; font-size: 13px; font-weight: 550; min-height: 38px; }
.primary:hover:enabled { background: color-mix(in srgb, var(--accent) 88%, black); }
.walkthrough-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 17px; gap: 12px; }
.walkthrough-heading h2 { margin: 6px 0 0; font-size: 21px; font-weight: 550; letter-spacing: -.6px; }
.steps { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border: 1px solid var(--sep); border-radius: 8px 8px 0 0; background: var(--card); overflow: hidden; }
.steps button { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 15px 6px; border: 0; border-bottom: 2px solid transparent; background: transparent; font-size: 12px; color: var(--text2); white-space: nowrap; }
.steps button.current { border-bottom-color: var(--accent); color: var(--accent); background: color-mix(in srgb, var(--blue-bg) 35%, var(--card)); }
.steps button:disabled { opacity: .6; }
.step-number { display: grid; place-items: center; width: 20px; height: 20px; border: 1px solid var(--sep-strong); border-radius: 50%; font-size: 11px; }
.current .step-number { background: var(--accent); color: white; border-color: var(--accent); }
.complete .step-number { background: var(--green-bg); color: var(--green); border-color: transparent; }
.workspace { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(300px, 1fr); border: 1px solid var(--sep); border-top: 0; border-radius: 0 0 9px 9px; overflow: hidden; background: var(--card); }
.work-panel { min-width: 0; }
.panel-bar { min-height: 47px; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--sep); font-size: 12px; }
.panel-bar > span:first-child { display: flex; align-items: center; gap: 7px; }
.muted { color: var(--text3); }
.sample-pill { font-size: 10px; color: var(--text3); letter-spacing: 1px; }
.avatar { height: 32px; width: 32px; display: inline-grid; place-items: center; flex-shrink: 0; border-radius: 50%; background: var(--blue-bg); color: var(--blue); font-size: 12px; font-weight: 600; }
.avatar.small { height: 22px; width: 22px; font-size: 9px; }
.avatar.large { height: 45px; width: 45px; font-size: 14px; }
.avatar.customer { background: var(--amber-bg); color: var(--amber); }
.scene { padding: 27px 25px 20px; min-height: 505px; display: flex; flex-direction: column; }
.scene-heading { display: flex; align-items: center; gap: 11px; margin-bottom: 23px; }
.scene-heading .eyebrow { font-size: 10px; letter-spacing: 1.25px; }
.scene h3 { margin: 4px 0 0; font-size: 17px; font-weight: 550; letter-spacing: -.45px; line-height: 1.35; }
.timestamp { margin-left: auto; color: var(--text3); font-size: 11px; }
.email { border: 1px solid var(--sep); border-radius: 7px; padding: 17px 20px; }
.email-from { display: flex; align-items: center; gap: 9px; }
.email-from strong { display: block; font-size: 13px; font-weight: 600; }
.email-from > div > span { display: block; color: var(--text3); font-size: 11px; margin-top: 2px; }
.new-pill { font-size: 10px; padding: 3px 7px; background: var(--blue-bg); color: var(--blue); border-radius: 4px; margin-left: auto; white-space: nowrap; }
.email h4 { font-size: 14px; font-weight: 600; margin: 16px 0 8px; }
.email p { font-size: 13px; line-height: 1.8; color: var(--text2); margin: 8px 0; }
.email-meta { display: flex; gap: 6px; align-items: center; font-size: 11px; color: var(--text3); margin-top: 14px; }
.extraction { margin: 17px 0; padding: 15px 17px; background: color-mix(in srgb, var(--blue-bg) 30%, var(--card)); border: 1px solid color-mix(in srgb, var(--accent) 17%, var(--sep)); border-radius: 7px; }
.extraction > div:first-child { display: flex; align-items: center; gap: 7px; color: var(--accent); font-size: 13px; }
.extraction > p { font-size: 12px; color: var(--text2); margin: 6px 0 13px; }
.fact-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.fact-grid span { font-size: 11px; color: var(--text3); }
.fact-grid strong { display: block; color: var(--text); font-size: 12px; margin-top: 2px; font-weight: 550; }
.scene-footer { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: auto; padding-top: 18px; }
.scene-footer > span { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text3); }
.assistant-panel { border-left: 1px solid var(--sep); display: flex; flex-direction: column; background: color-mix(in srgb, var(--sunk) 30%, var(--card)); min-width: 0; }
.assistant-heading { display: flex; align-items: center; gap: 9px; padding: 17px 20px 13px; }
.assistant-symbol { width: 31px; height: 31px; border-radius: 8px; background: #15374a; color: #e9f0f4; display: grid; place-items: center; }
.assistant-heading h3 { font-size: 14px; font-weight: 600; margin: 0; }
.assistant-heading > div > span { color: var(--text3); font-size: 10px; }
.channel-tabs { display: flex; gap: 8px; margin: 0 18px; padding-bottom: 12px; border-bottom: 1px solid var(--sep); }
.channel-tabs button { flex: 1; padding: 7px 5px; font-size: 11px; border: 1px solid transparent; background: none; color: var(--text2); border-radius: 5px; display: flex; justify-content: center; align-items: center; gap: 5px; }
.channel-tabs button.active { background: var(--card); border-color: var(--sep); color: var(--text); box-shadow: 0 1px 2px #00000006; }
.conversation { padding: 16px 19px 20px; display: flex; flex-direction: column; gap: 13px; flex: 1; }
.conversation-date { display: block; text-align: center; font-size: 9px; color: var(--text3); letter-spacing: 1px; margin-bottom: 5px; }
.message { max-width: 95%; border-radius: 8px; padding: 10px 12px; font-size: 12px; border: 1px solid var(--sep); }
.message p { margin: 4px 0; line-height: 1.7; }
.assistant-message { background: var(--card); align-self: flex-start; }
.user-message { background: var(--green-bg); border-color: color-mix(in srgb, var(--green) 15%, var(--sep)); align-self: flex-end; }
.message-author { font-size: 10px; font-weight: 600; color: var(--text2); }
.message-time { display: flex; align-items: center; justify-content: flex-end; gap: 3px; font-size: 9px; color: var(--text3); margin-top: 8px; }
.evidence-tag, .approval-chip { display: inline-flex; gap: 4px; align-items: center; padding: 4px 6px; border-radius: 4px; font-size: 10px; background: var(--sunk); color: var(--text2); margin-top: 5px; }
.approval-chip { background: var(--amber-bg); color: var(--amber); }
.final-message { border-color: color-mix(in srgb, var(--green) 40%, var(--sep)); }
.assistant-bottom { border-top: 1px solid var(--sep); display: flex; align-items: center; gap: 9px; padding: 15px 20px; color: var(--text3); font-size: 10px; }
.assistant-bottom > :global(svg) { color: var(--green); }
.assistant-bottom strong { color: var(--text2); font-size: 10px; font-weight: 500; }
.lead-card { border: 1px solid var(--sep); border-radius: 8px; overflow: hidden; }
.lead-identity { display: flex; align-items: center; gap: 11px; padding: 18px; }
.lead-identity h4 { margin: 0; font-size: 16px; font-weight: 550; }
.lead-identity > div > span { font-size: 11px; color: var(--text3); }
.property-visual { display: flex; align-items: center; gap: 18px; padding: 22px; background: var(--blue-bg); color: var(--blue); }
.property-visual > div > span { font-size: 10px; letter-spacing: 2px; }
.property-visual strong { display: block; font-size: 21px; letter-spacing: -.5px; font-weight: 500; margin-top: 3px; }
.property-visual p { font-size: 12px; margin: 6px 0 0; }
.lead-details { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; padding: 19px; margin: 0; }
.lead-details dt { font-size: 11px; color: var(--text3); margin-bottom: 3px; }
.lead-details dd { font-size: 12px; margin: 0; overflow-wrap: anywhere; }
.activity { display: flex; align-items: center; gap: 8px; padding: 14px 18px; border-top: 1px solid var(--sep); color: var(--green); }
.activity strong, .activity span { display: block; font-size: 12px; font-weight: 500; }
.activity span { color: var(--text3); font-size: 10px; margin-top: 2px; }
.next-request { display: flex; align-items: center; gap: 9px; margin-top: 16px; color: var(--green); }
.next-request p { font-size: 12px; line-height: 1.8; color: var(--text2); margin: 0; }
.next-request strong { font-weight: 500; color: var(--text); }
.calendar { border: 1px solid var(--sep); border-radius: 7px; padding: 17px; }
.calendar-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 20px; }
.calendar-head strong { font-size: 14px; font-weight: 600; }
.calendar-head > div > span { display: block; font-size: 11px; color: var(--text3); margin-top: 3px; }
.calendar-provider { font-size: 10px; color: var(--text2); }
.calendar-row { display: flex; gap: 13px; margin-top: 9px; }
.calendar-row time { width: 34px; padding-top: 9px; font-size: 11px; color: var(--text3); flex-shrink: 0; }
.calendar-event { border-left: 3px solid var(--blue); border-radius: 4px; padding: 10px 12px; flex: 1; position: relative; }
.calendar-event strong { font-size: 12px; font-weight: 550; display: block; }
.calendar-event > span { display: block; font-size: 10px; margin-top: 4px; }
.blue-event { background: var(--blue-bg); color: var(--blue); }
.busy-event { background: var(--amber-bg); color: var(--amber); border-color: var(--amber); }
.proposed-event { background: var(--green-bg); color: var(--green); border-color: var(--green); border-left-style: dashed; }
.calendar-event > .conflict-label { position: absolute; top: 5px; right: 10px; font-size: 9px; }
.slot-picker { border: 0; padding: 0; margin: 21px 0 12px; display: flex; gap: 8px; }
.slot-picker legend { font-size: 12px; margin-bottom: 9px; font-weight: 550; }
.slot { display: flex; align-items: center; gap: 12px; padding: 10px; background: var(--card); border: 1px solid var(--sep); border-radius: 5px; font-size: 14px; min-height: 38px; }
.slot > span { color: var(--text3); font-size: 10px; }
.slot.selected { background: var(--blue-bg); border-color: var(--accent); color: var(--accent); }
.slot.selected > span { color: var(--accent); }
.slot.busy { background: var(--sunk); }
.small-note { font-size: 11px; display: flex; align-items: center; gap: 6px; color: var(--text3); margin: 0; }
.approval-summary { display: flex; align-items: center; gap: 18px; padding: 18px; border: 1px solid var(--sep); border-radius: 8px; }
.approval-date { display: flex; flex-direction: column; align-items: center; width: 48px; flex-shrink: 0; }
.approval-date span { font-size: 11px; color: var(--text3); letter-spacing: 1px; }
.approval-date strong { font-size: 30px; line-height: 1.3; font-weight: 500; }
.approval-summary h4 { font-size: 13px; font-weight: 550; margin: 0 0 7px; }
.approval-summary p { font-size: 12px; color: var(--text2); margin: 3px 0; }
.approval-options { margin: 21px 0 15px; padding: 0; border: 0; }
.approval-options legend { font-size: 12px; font-weight: 550; margin-bottom: 11px; }
.approval-options label { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; cursor: pointer; }
.approval-options input { width: 14px; height: 14px; accent-color: var(--accent); }
.approval-options strong { display: block; font-size: 12px; font-weight: 500; }
.approval-options small { display: block; font-size: 10px; color: var(--text3); margin-top: 2px; }
.reply-label { display: block; font-size: 11px; color: var(--text2); margin-bottom: 6px; }
textarea { width: 100%; min-height: 88px; padding: 12px; border: 1px solid var(--sep-strong); border-radius: 6px; background: var(--card); font: inherit; font-size: 13px; line-height: 1.7; color: var(--text); resize: vertical; }
.approval-note { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text3); margin: 14px 0; }
.completed-scene { align-items: center; text-align: center; padding-top: 35px; }
.completion-icon { width: 60px; height: 60px; display: grid; place-items: center; background: var(--green-bg); color: var(--green); border-radius: 50%; margin-bottom: 18px; }
.completed-scene h3 { font-size: 26px; margin-top: 13px; line-height: 1.3; letter-spacing: -.7px; }
.completed-scene > p { font-size: 13px; color: var(--text2); line-height: 1.7; margin: 12px 0 21px; }
.completion-receipts { width: 100%; border: 1px solid var(--sep); border-radius: 7px; text-align: left; margin: 0 0 16px; }
.completion-receipts > div { display: flex; align-items: center; gap: 9px; padding: 13px; border-bottom: 1px solid var(--sep); color: var(--green); }
.completion-receipts > div:last-child { border: 0; }
.completion-receipts strong { display: block; color: var(--text); font-size: 12px; font-weight: 500; }
.completion-receipts small { display: block; color: var(--text3); font-size: 10px; margin-top: 3px; overflow-wrap: anywhere; }
.receipt-pill { font-size: 9px; border: 1px solid var(--sep); padding: 3px 5px; color: var(--text3); border-radius: 4px; margin-left: auto; flex-shrink: 0; }
.completed-scene > .small-note { font-size: 11px; margin: 1px 0 18px; }
.customer-thread-heading { display: flex; gap: 8px; align-items: center; margin: 0 0 15px; }
.customer-thread-heading strong { display: block; font-size: 13px; font-weight: 550; }
.customer-thread-heading > div > span { display: block; font-size: 10px; color: var(--text3); margin-top: 2px; }
.customer-empty { text-align: center; color: var(--text3); margin: 25px 0; display: grid; justify-items: center; gap: 7px; }
.customer-empty p { font-size: 12px; line-height: 1.7; }
.customer-boundary { display: flex; align-items: flex-start; gap: 6px; font-size: 10px; color: var(--text3); margin-top: auto; }
.demo-footer { display: flex; justify-content: space-between; gap: 18px; margin-top: 22px; padding-top: 19px; font-size: 10px; color: var(--text3); border-top: 1px solid var(--sep); }
.demo-footer > span:first-child { display: flex; gap: 6px; align-items: center; }
.reconnect { display: flex; gap: 8px; align-items: center; background: var(--amber-bg); color: var(--amber); padding: 12px 18px; font-size: 13px; }
.connection-dialog { width: min(480px, calc(100vw - 32px)); border: 1px solid var(--sep); border-radius: 12px; padding: 26px; background: var(--card); color: var(--text); box-shadow: 0 20px 100px #00000033; }
.connection-dialog::backdrop { background: #0b172c66; backdrop-filter: blur(3px); }
.dialog-heading { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.connection-dialog h2 { font-size: 25px; font-weight: 550; letter-spacing: -.7px; margin: 8px 0 10px; }
.connection-dialog > p { font-size: 13px; line-height: 1.8; color: var(--text2); margin-bottom: 21px; }
.provider-choice { padding: 0; margin: 0 0 20px; border: 0; display: flex; gap: 8px; }
.provider-choice legend { font-size: 12px; color: var(--text2); margin-bottom: 10px; }
.provider-choice button { display: flex; align-items: center; gap: 8px; flex: 1; border: 1px solid var(--sep); padding: 11px; border-radius: 6px; background: var(--card); font-size: 12px; color: var(--text); }
.provider-choice button.selected { border-color: var(--accent); background: var(--blue-bg); color: var(--accent); }
.permission { display: flex; align-items: center; gap: 8px; font-size: 12px; margin-top: 12px; color: var(--text2); }
.permission > :global(svg) { color: var(--green); flex-shrink: 0; }
.dialog-actions { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding-top: 23px; margin-top: 23px; border-top: 1px solid var(--sep); }
.whatsapp-modes { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 20px 0; }
.whatsapp-modes > div { border: 1px solid var(--sep); border-radius: 7px; padding: 13px; color: var(--green); }
.whatsapp-modes strong { display: block; font-size: 13px; font-weight: 550; color: var(--text); margin-top: 10px; }
.whatsapp-modes p { font-size: 12px; color: var(--text2); margin: 5px 0 0; line-height: 1.7; }
.presenter .intro { display: none; }
.presenter .demo-main { max-width: 1600px; padding-top: 25px; }
.presenter .connections { margin-bottom: 24px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
@media (min-width: 1600px) { .demo-main { padding-top: 50px; } .scene { min-height: 550px; } }
@media (max-width: 900px) { .demo-main { padding: 30px 24px 20px; } .demo-nav { padding: 0 24px; } .intro-note { min-width: 230px; } .workspace { grid-template-columns: minmax(0, 1.3fr) minmax(270px, 1fr); } .scene { padding: 22px 18px 18px; } .connection-card { padding: 14px; } .connection-caption { min-height: 40px; } .scene h3 { font-size: 16px; } .connection-status { font-size: 10px; } .demo-footer { flex-direction: column; gap: 10px; } }
@media (max-width: 700px) { .demo-nav { height: 66px; padding: 0 17px; gap: 8px; } .brand { font-size: 22px; gap: 7px; } .enterprise, .brand-divider, .presenter-button { display: none; } .nav-actions { gap: 4px; } .demo-label { font-size: 11px; padding: 4px 6px; } .demo-main { padding: 27px 17px 20px; } .intro-note { display: none; } h1 { font-size: 37px; } .intro { margin-bottom: 24px; } .connections { grid-template-columns: 1fr; gap: 9px; margin-bottom: 28px; } .connection-card { position: relative; padding: 13px 15px 12px 65px; } .connection-top { position: static; } .connection-icon { position: absolute; top: 14px; left: 15px; } .connection-status { position: absolute; right: 15px; top: 15px; } .connection-title { margin-top: 2px; padding-right: 0; } .connection-title h2 { font-size: 14px; } .connection-title .text-button { margin-top: 19px; font-size: 11px; } .account { margin-top: -10px; margin-bottom: 7px; padding-right: 50px; font-size: 11px; } .connection-caption { border: 0; padding: 0; min-height: 0; font-size: 11px; } .walkthrough-heading { align-items: flex-start; } .walkthrough-heading h2 { font-size: 17px; max-width: 230px; } .walkthrough-heading .quiet { white-space: nowrap; font-size: 10px; padding: 4px 0; } .eyebrow { font-size: 10px; letter-spacing: 1.2px; } .workspace { grid-template-columns: 1fr; } .assistant-panel { border-left: 0; border-top: 1px solid var(--sep); } .steps button { flex-direction: column; gap: 7px; font-size: 10px; padding: 12px 2px; white-space: normal; text-align: center; } .steps button > span:last-child { max-width: 60px; } .scene { min-height: 480px; padding: 23px 15px 18px; } .scene h3 { font-size: 15px; } .sample-pill { display: none; } .panel-bar { padding: 0 15px; } .email { padding: 15px; } .fact-grid { gap: 12px 8px; } .fact-grid strong { font-size: 11px; } .slot { flex: 1; gap: 6px; padding: 10px 7px; font-size: 13px; } .slot > span { font-size: 9px; } .scene-footer > span { max-width: 160px; font-size: 10px; } .scene-footer .primary { padding: 10px 11px; font-size: 12px; } .lead-details { gap: 14px 10px; padding: 15px; } .lead-details dd { font-size: 11px; } .approval-summary { gap: 12px; padding: 14px; } .approval-summary h4 { font-size: 13px; } .approval-summary p { font-size: 11px; } .calendar-event > .conflict-label { position: static; } .calendar-provider { max-width: 75px; text-align: right; } .completed-scene h3 { font-size: 22px; } .receipt-pill { display: none; } .connection-dialog { padding: 22px; } .whatsapp-modes { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { button { transition: none; } .connection-dialog::backdrop { backdrop-filter: none; } }
</style>
