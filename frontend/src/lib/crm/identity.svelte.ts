import { getQueryClient } from '$lib/queries/client'
import { subscribeUser } from '$lib/stores/user.svelte'

export const crmIdentity = $state({ key: '', userId: '', organizationId: '', generation: 0 })
const listeners = new Set<() => void>()

export function onCrmIdentityChange(listener: () => void): () => void {
	listeners.add(listener)
	return () => {
		listeners.delete(listener)
	}
}

subscribeUser((user) => {
	const key =
		user?.id && user.organization_id
			? JSON.stringify([
					user.id,
					user.organization_id,
					user.role,
					user.is_owner,
					user.subscription_status
				])
			: ''
	if (key === crmIdentity.key) return
	crmIdentity.key = key
	crmIdentity.userId = user?.id ?? ''
	crmIdentity.organizationId = user?.organization_id ?? ''
	crmIdentity.generation += 1
	const client = getQueryClient()
	void client.cancelQueries({ queryKey: ['crm'] })
	client.removeQueries({ queryKey: ['crm'] })
	for (const listener of listeners) listener()
})

export const crmScopeKey = () =>
	['crm', crmIdentity.userId, crmIdentity.organizationId, crmIdentity.generation] as const
export const crmIdentityKnown = () => Boolean(crmIdentity.key)
