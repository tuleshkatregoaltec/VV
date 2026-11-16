<script lang="ts">
/** My profile inside the CRM shell, so opening it from the CRM profile menu keeps the CRM sidebar. */
import PageContainer from '$lib/components/layout/PageContainer.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import ProfilePage from '../../profile/+page.svelte'
</script>
<PageHeader title="Profile" />
<PageContainer variant="fullBleed">
	<ProfilePage />
</PageContainer>
