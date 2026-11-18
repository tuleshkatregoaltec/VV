<script lang="ts">
import ArrowUpRight from 'lucide-svelte/icons/arrow-up-right'
import CalendarDays from 'lucide-svelte/icons/calendar-days'
import Mail from 'lucide-svelte/icons/mail'
import MessageCircle from 'lucide-svelte/icons/message-circle'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
</script>

<PageHeader title="Connectors" facts="Email, calendar and WhatsApp" />
<section class="card connector-preview">
	<span class="chip green">Available</span>
	<h2>Email your leads.</h2>
	<p>Send marketing, reports and updates through Brevo, with delivery, opens and clicks tracked. You see only the leads assigned to you or your teams.</p>
	<a class="btn" href="/crm/connectors/email"><Mail size={15} /> Open Email</a>
</section>
<section class="card connector-preview">
	<span class="chip green">Available</span>
	<h2>Connect your Google Calendar.</h2>
	<p>Viewings, calls and follow-ups you add in the CRM appear in your own Google Calendar, and changes made there come back.</p>
	<a class="btn" href="/crm/calendar"><CalendarDays size={15} /> Open Calendar</a>
</section>
<section class="card connector-preview">
	<span class="chip green">Available</span>
	<h2>Connect your WhatsApp.</h2>
	<p>Answer buyer enquiries from your own WhatsApp number. Choose who is never read, then turn replies on when you are ready.</p>
	<a class="btn" href="/crm/whatsapp"><MessageCircle size={15} /> Connect WhatsApp</a>
</section>
<section class="card connector-preview">
	<span class="chip outline">Interactive preview</span>
	<h2>A connected day, from enquiry to viewing.</h2>
	<p>Explore the planned experience with sample accounts, a portal enquiry, a private assistant and an approved viewing.</p>
	<div class="channels"><span><Mail size={18} /> Gmail / Outlook</span><span><CalendarDays size={18} /> Google / Microsoft Calendar</span><span><MessageCircle size={18} /> WhatsApp Business</span></div>
	<a class="btn" href="/demo/assistant" target="_blank" rel="noopener noreferrer">Open enterprise demo <ArrowUpRight size={15} /></a>
	<p class="small muted">Provider connections are simulated. No real messages are sent or bookings created.</p>
</section>

<style>
.connector-preview { padding: 32px; max-width: 900px; }
h2 { font-size: 26px; font-weight: 550; margin: 18px 0 10px; letter-spacing: -.6px; }
p { color: var(--text2); max-width: 600px; font-size: 13px; line-height: 1.8; }
.channels { display: flex; flex-wrap: wrap; gap: 14px 25px; margin: 28px 0; }
.channels > span { display: flex; align-items: center; gap: 8px; font-size: 12px; }
a.btn { display: inline-flex; gap: 10px; text-decoration: none; }
.small { font-size: 11px; margin-top: 20px; }
@media(max-width: 600px) { .connector-preview { padding: 22px; } h2 { font-size: 22px; } }
</style>
