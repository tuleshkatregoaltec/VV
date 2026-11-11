<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crmQueries } from '$lib/crm/queries'

const counts = createQuery(() => crmQueries.counts())
const leads = createQuery(() => crmQueries.leads({ stage: 'new' }))
const deals = createQuery(() => crmQueries.deals('conveyancing'))
let selected = $state<'day' | 'leads' | 'deals'>('day')
const questions = {
	day: 'What should I prioritise today?',
	leads: 'Which new enquiries should I review first?',
	deals: 'What is moving through conveyancing?'
}
</script>

<section class="card briefing" aria-label="CRM briefing">
 <div class="ch"><h2>Daily briefing</h2><span class="small muted">Your pipeline at a glance</span></div>
 <div class="conversation">
  <div class="question">{questions[selected]}</div>
  <div class="answer">
   {#if selected === 'day'}
    <p>You have <b>{counts.data?.new_leads ?? 0} new leads</b>, <b>{counts.data?.events_today ?? 0} appointments today</b> and <b>{counts.data?.open_deals ?? 0} open deals</b>.</p>
    <p>Start with new enquiries, confirm today's viewing arrangements, then review the next conveyancing milestones.</p>
   {:else if selected === 'leads'}
    <p>Start with these enquiries:</p>
    {#each leads.data?.items.slice(0, 4) ?? [] as lead (lead.id)}
     <a href="/crm/leads?lead={lead.id}"><b>{lead.name}</b> · {lead.summary.line}<span>{lead.summary.sub} · {lead.next_action}</span></a>
    {/each}
   {:else}
    <p>Upcoming deal milestones:</p>
    {#each deals.data?.items.slice(0, 4) ?? [] as deal (deal.id)}
     <a href="/crm/deals?deal={deal.id}"><b>{deal.unit}</b> · {deal.client}<span>{deal.stage} → {deal.next_step}</span></a>
    {/each}
   {/if}
  </div>
 </div>
 <div class="prompts">
  {#each Object.entries(questions) as [key, question] (key)}
   <button type="button" class="btn ghost" onclick={() => selected = key as typeof selected}>{question}</button>
  {/each}
 </div>
</section>

<style>
.briefing { max-width: 1050px; min-height: 520px; }
.conversation { padding: 28px; display: grid; gap: 22px; }
.question { justify-self: end; padding: 15px 20px; border-radius: 10px; background: var(--text); color: var(--bg); max-width: 75%; }
.answer { padding: 22px; border: 1px solid var(--sep); border-radius: 10px; line-height: 1.8; max-width: 85%; background: var(--bg); }
p + p { margin-top: 12px; }
a { display: block; color: inherit; padding: 12px 0; text-decoration: none; border-bottom: 1px solid var(--sep); }
a span { display: block; color: var(--text2); font-size: 12px; }
.prompts { display: flex; flex-wrap: wrap; gap: 8px; padding: 20px 28px; border-top: 1px solid var(--sep); }
</style>
