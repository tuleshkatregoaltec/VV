<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Building2 from 'lucide-svelte/icons/building-2'
import CalendarDays from 'lucide-svelte/icons/calendar-days'
import ChartNoAxesColumn from 'lucide-svelte/icons/chart-no-axes-column'
import CircleDot from 'lucide-svelte/icons/circle-dot'
import FileText from 'lucide-svelte/icons/file-text'
import House from 'lucide-svelte/icons/house'
import Inbox from 'lucide-svelte/icons/inbox'
import LayoutGrid from 'lucide-svelte/icons/layout-grid'
import MessageCircle from 'lucide-svelte/icons/message-circle'
import Plug from 'lucide-svelte/icons/plug'
import Send from 'lucide-svelte/icons/send'
import User from 'lucide-svelte/icons/user'
import { page } from '$app/state'
import ProfileDropdown from '$lib/components/navigation/ProfileDropdown.svelte'
import SectionSwitch from '$lib/components/navigation/SectionSwitch.svelte'
import type { Me, NavCounts } from '../../api/types'
import { crmQueries } from '../../queries'
import { chrome } from '../../stores/chrome.svelte'

let { counts, me }: { counts: NavCounts | undefined; me: Me | undefined } = $props()

/**
 * What to show comes from the server's assignment scope; the pages check access themselves, so
 * hiding an entry here never grants or denies anything. Until the scope loads, only agent entries
 * show, so a manager's sidebar grows rather than an agent's shrinking.
 */
const scope = createQuery(() => crmQueries.assignmentScope())
const caps = $derived(scope.data?.capabilities)
const roleLabel = $derived(
	caps?.organization_admin
		? me?.is_owner
			? 'Owner'
			: 'Administrator'
		: caps?.can_assign
			? 'Manager'
			: 'Agent'
)

interface Item {
	href: string
	label: string
	icon: typeof House
	count: number | null
	countLabel?: string
}

/** Group CRM workflows by purpose, following the Market sidebar hierarchy. */
const groups = $derived<{ label: string; items: Item[] }[]>([
	{
		label: 'CRM',
		items: [{ href: '/crm', label: 'Home', icon: House, count: null }]
	},
	{
		label: 'Leads and contacts',
		items: [
			{
				href: '/crm/leads',
				label: 'Leads',
				icon: User,
				count: counts?.new_leads ?? null,
				countLabel: counts?.limited ? 'new in loaded leads' : 'new'
			},
			{
				href: '/crm/inbox',
				label: 'Inbox',
				icon: Inbox,
				count: counts?.inbox ?? null,
				countLabel: 'open'
			},
			{ href: '/crm/matches', label: 'Matches', icon: CircleDot, count: null },
			{ href: '/crm/owners', label: 'Owners', icon: Building2, count: null }
		]
	},
	{
		label: 'Deals and properties',
		items: [
			{
				href: '/crm/deals',
				label: 'Deals',
				icon: FileText,
				count: counts?.open_deals ?? null,
				countLabel: 'open'
			},
			{ href: '/crm/assets', label: 'Assets', icon: LayoutGrid, count: null }
		]
	},
	{
		label: 'Tools',
		items: [
			{
				href: '/crm/calendar',
				label: 'Calendar',
				icon: CalendarDays,
				count: counts?.events_today ?? null,
				countLabel: 'today'
			},
			{ href: '/crm/assistant', label: 'Assistant', icon: Send, count: null },
			{ href: '/crm/whatsapp', label: 'WhatsApp', icon: MessageCircle, count: null }
		]
	},
	{
		// Manager view only for people who can assign (managers and administrators). Lead routing has
		// no page of its own: rules sit in Organisation settings and are applied where leads are issued.
		// Connectors (each person's own channels) stays for everyone.
		label: 'Management',
		items: [
			...(caps?.can_assign
				? [
						{
							href: '/crm/settings',
							label: 'Manager view',
							icon: ChartNoAxesColumn,
							count: counts?.waiting ?? null,
							countLabel: 'waiting to assign'
						}
					]
				: []),
			{ href: '/crm/connectors', label: 'Connectors', icon: Plug, count: null }
		]
	}
])

const path = $derived(page.url.pathname.replace(/\/$/, ''))
</script>

<aside class="sb" aria-label="CRM">
	<div class="sb-head">
		<a class="logo" href="/crm" aria-label="Vitevue CRM home"><i>V</i><span class="lt">itevue</span></a>
		<div class="sb-switch"><SectionSwitch current="crm" /></div>
	</div>
	<nav aria-label="CRM sections">
		{#each groups as g (g.label)}
			<div class="sb-grp">{g.label}</div>
			{#each g.items as it (it.href)}
				<a
					class="nav-i"
					href={it.href}
					title={it.label}
					aria-current={path === it.href ||
						(it.href !== '/crm' && path.startsWith(`${it.href}/`)) ||
						// An agent's analytics page belongs to Manager view.
						(it.href === '/crm/settings' && path.startsWith('/crm/team/'))
							? 'page'
							: undefined}
					onclick={() => (chrome.sbOpen = false)}
				>
					<it.icon size={16} aria-hidden="true" />
					<span class="lbltxt">{it.label}</span>
					{#if it.count}<span class="ct" aria-label="{it.count} {it.countLabel}">{it.count}</span>{/if}
				</a>
			{/each}
		{/each}
	</nav>
	<div class="sb-foot">
		<!-- Same profile menu as the Market sidebar (My profile, Settings, Sign out). -->
		<ProfileDropdown />
		<span class="who"><b>{me?.name ?? ''}</b><br /><span class="muted">{roleLabel}{me?.areas.length ? ` · ${me.areas.join(', ')}` : ''}</span></span>
	</div>
</aside>
<button
	type="button"
	class="sb-scrim"
	aria-label="Close the sidebar"
	tabindex="-1"
	onclick={() => (chrome.sbOpen = false)}
></button>
