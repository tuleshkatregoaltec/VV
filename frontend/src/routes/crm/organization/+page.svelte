<script lang="ts">
/**
 * Organisation settings and set-up inside the CRM shell (/crm/settings is the Manager view).
 * Tabs follow what the person may do: owners see General; owners and administrators build the
 * hierarchy and teams; anyone who can assign leads configures routing, languages and sees workload.
 * Routing itself is applied where leads are issued (Leads imports), not from a page of its own.
 */

import { createQuery } from '@tanstack/svelte-query'
import { replaceState } from '$app/navigation'
import { page } from '$app/state'
import PageContainer from '$lib/components/layout/PageContainer.svelte'
import AgentLanguages from '$lib/crm/components/manager/AgentLanguages.svelte'
import OrgHierarchy from '$lib/crm/components/manager/OrgHierarchy.svelte'
import RoutingSettings from '$lib/crm/components/manager/RoutingSettings.svelte'
import TeamsSettings from '$lib/crm/components/manager/TeamsSettings.svelte'
import TeamWorkload from '$lib/crm/components/manager/TeamWorkload.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import { crmQueries } from '$lib/crm/queries'
import { currentUser } from '$lib/stores/user.svelte'
import OrganizationSettingsPage from '../../settings/organization/+page.svelte'

type Section = 'general' | 'hierarchy' | 'teams' | 'routing' | 'languages' | 'workload'

const scope = createQuery(() => crmQueries.assignmentScope())
const isOwner = $derived(Boolean(currentUser.data?.is_owner))

const sections = $derived.by(() => {
	const caps = scope.data?.capabilities
	const out: { id: Section; label: string }[] = []
	if (isOwner) out.push({ id: 'general', label: 'General' })
	if (isOwner || caps?.can_manage_teams) {
		out.push({ id: 'hierarchy', label: 'Hierarchy' }, { id: 'teams', label: 'Teams & members' })
	}
	if (caps?.can_assign) {
		out.push(
			{ id: 'routing', label: 'Routing rules' },
			{ id: 'languages', label: 'Agent languages' },
			{ id: 'workload', label: 'Team workload' }
		)
	}
	return out
})

let chosen = $state<Section | null>(null)
let editTeamId = $state('')
const requested = $derived(page.url.searchParams.get('tab') as Section | null)
const section = $derived.by(() => {
	const want = chosen ?? requested
	return sections.find((s) => s.id === want)?.id ?? sections[0]?.id ?? null
})

function select(id: Section) {
	chosen = id
	const url = new URL(page.url)
	url.searchParams.set('tab', id)
	replaceState(url, page.state)
}

function editTeam(teamId: string) {
	editTeamId = teamId
	select('teams')
}
</script>

<svelte:head><title>Organisation Settings · CRM Beta</title></svelte:head>

<PageHeader title="Organization Settings" />
<PageContainer variant="fullBleed">
	<QueryView query={scope}>
		{#snippet children(data)}
			{#if section}
				<Tabs items={sections} value={section} onselect={select} label="Organization settings" />
				<div class="section">
					{#if section === 'general'}
						<OrganizationSettingsPage />
					{:else if section === 'hierarchy'}
						<OrgHierarchy onEditTeam={editTeam} />
					{:else if section === 'teams'}
						<TeamsSettings teamId={editTeamId} />
					{:else if section === 'routing'}
						<RoutingSettings
							editable={data.capabilities.can_manage_rules}
							canManageTeams={data.capabilities.can_manage_teams}
						/>
					{:else if section === 'languages'}
						<AgentLanguages />
					{:else}
						<TeamWorkload />
					{/if}
				</div>
			{:else}
				<h1 class="text-2xl font-semibold">Organisation settings</h1>
				<p>Only organisation owners, administrators and team supervisors can change organisation settings.</p>
			{/if}
		{/snippet}
	</QueryView>
</PageContainer>

<style>
	.section {
		margin-top: 16px;
		padding-bottom: 88px;
	}
</style>
