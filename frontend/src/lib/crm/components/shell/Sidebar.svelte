<script lang="ts">
import Building2 from 'lucide-svelte/icons/building-2'
import CalendarDays from 'lucide-svelte/icons/calendar-days'
import ChartLine from 'lucide-svelte/icons/chart-line'
import ChartNoAxesColumn from 'lucide-svelte/icons/chart-no-axes-column'
import CircleDot from 'lucide-svelte/icons/circle-dot'
import FileChartColumn from 'lucide-svelte/icons/file-chart-column'
import FileText from 'lucide-svelte/icons/file-text'
import Grid2x2 from 'lucide-svelte/icons/grid-2x2'
import Hotel from 'lucide-svelte/icons/hotel'
import House from 'lucide-svelte/icons/house'
import Inbox from 'lucide-svelte/icons/inbox'
import LandPlot from 'lucide-svelte/icons/land-plot'
import LayoutGrid from 'lucide-svelte/icons/layout-grid'
import List from 'lucide-svelte/icons/list'
import MessageSquare from 'lucide-svelte/icons/message-square'
import Radar from 'lucide-svelte/icons/radar'
import Send from 'lucide-svelte/icons/send'
import SlidersHorizontal from 'lucide-svelte/icons/sliders-horizontal'
import Table from 'lucide-svelte/icons/table'
import User from 'lucide-svelte/icons/user'
import { page } from '$app/state'
import type { Me, NavCounts } from '../../api/types'
import { MARKET_SCREENS } from '../../market/data'
import { chrome } from '../../stores/chrome.svelte'

let { counts, me }: { counts: NavCounts | undefined; me: Me | undefined } = $props()

interface Item {
	href: string
	label: string
	icon: typeof House
	count: number | null
	countLabel?: string
}

/**
 * v2 sidebar (6 Oct): Agent · Home, Leads, Inbox, Matches, Owners, Deals, Calendar; Assets stays
 * until the founders decide (open question 3). Manager · Settings holds the lead handout setting
 * the Inbox depends on. Counts: new leads, inbox waiting for me, open deals, today's events.
 */
const groups = $derived<{ label: string; items: Item[] }[]>([
	{
		label: 'Agent',
		items: [
			{ href: '/crm', label: 'Home', icon: House, count: null },
			{
				href: '/crm/leads',
				label: 'Leads',
				icon: User,
				count: counts?.new_leads ?? null,
				countLabel: 'new'
			},
			{
				href: '/crm/inbox',
				label: 'Inbox',
				icon: Inbox,
				count: counts?.inbox ?? null,
				countLabel: 'open'
			},
			{ href: '/crm/matches', label: 'Matches', icon: CircleDot, count: null },
			{ href: '/crm/owners', label: 'Owners', icon: Building2, count: null },
			{
				href: '/crm/deals',
				label: 'Deals',
				icon: FileText,
				count: counts?.open_deals ?? null,
				countLabel: 'open'
			},
			{
				href: '/crm/calendar',
				label: 'Calendar',
				icon: CalendarDays,
				count: counts?.events_today ?? null,
				countLabel: 'today'
			},
			{ href: '/crm/assets', label: 'Assets', icon: LayoutGrid, count: null },
			{ href: '/crm/assistant', label: 'Assistant', icon: Send, count: null }
		]
	},
	{
		label: 'Manager',
		items: [
			{
				href: '/crm/manager',
				label: 'Manager view',
				icon: ChartNoAxesColumn,
				count: null
			},
			{
				href: '/crm/settings',
				label: 'Settings',
				icon: SlidersHorizontal,
				count: counts?.waiting ?? null,
				countLabel: 'waiting to assign'
			}
		]
	}
])

const MARKET_ICONS: Record<string, typeof House> = {
	home: Grid2x2,
	tx: Table,
	an: ChartLine,
	ls: List,
	unit: FileChartColumn,
	launch: Hotel,
	plots: LandPlot,
	radar: Radar,
	chat: MessageSquare
}

/** Market mode (call 6 Oct, 12:57): the same shell, its own sections, grouped as on the mockup. */
const marketGroups = MARKET_SCREENS.reduce<{ label: string; items: Item[] }[]>((acc, s) => {
	const item = { href: s.path, label: s.label, icon: MARKET_ICONS[s.id], count: null }
	const g = acc.find((x) => x.label === s.grp)
	if (g) g.items.push(item)
	else acc.push({ label: s.grp, items: [item] })
	return acc
}, [])

const path = $derived(page.url.pathname.replace(/\/$/, ''))
const isMarket = $derived(path === '/crm/market' || path.startsWith('/crm/market/'))
const shown = $derived(isMarket ? marketGroups : groups)
</script>

<aside class="sb" aria-label="CRM">
	<div class="sb-head">
		<a class="logo" href="/crm" aria-label="Vitevue CRM home"><i>V</i><span class="lt">itevue</span></a>
		<div class={['modesw', isMarket && 'market']} role="radiogroup" aria-label="Mode">
			<span class="modesw-pill" aria-hidden="true"></span>
			<a href="/crm" role="radio" aria-checked={!isMarket}>CRM</a>
			<a href="/crm/market" role="radio" aria-checked={isMarket}>Market</a>
		</div>
	</div>
	<nav aria-label={isMarket ? 'Market sections' : 'CRM sections'}>
		{#each shown as g (g.label)}
			<div class="sb-grp">{g.label}</div>
			{#each g.items as it (it.href)}
				<a
					class="nav-i"
					href={it.href}
					title={it.label}
					aria-current={path === it.href ? 'page' : undefined}
					onclick={() => (chrome.sbOpen = false)}
				>
					<it.icon size={17} aria-hidden="true" />
					<span class="lbltxt">{it.label}</span>
					{#if it.count}<span class="ct" aria-label="{it.count} {it.countLabel}">{it.count}</span>{/if}
				</a>
			{/each}
		{/each}
	</nav>
	<div class="sb-foot">
		<span class="avatar" aria-hidden="true">{me?.initials ?? ''}</span>
		<span class="who"><b>{me?.name ?? ''}</b><br /><span class="muted">Agent · {me?.areas.join(', ') ?? ''}</span></span>
	</div>
</aside>
<button
	type="button"
	class="sb-scrim"
	aria-label="Close the sidebar"
	tabindex="-1"
	onclick={() => (chrome.sbOpen = false)}
></button>
