import { crm } from './api'
import { write } from './write'

/** Connectors › Email writes shared by the page and its panels. */

/** Ask, then remove a sent email from Tracking. Resolves true when it was removed. */
export async function confirmDeleteSend(s: { id: number; subject: string; to_email: string }) {
	if (!confirm(`Delete "${s.subject}" to ${s.to_email} from Tracking? This cannot be undone.`))
		return false
	const r = await write({
		call: () => crm.email.removeSend(s.id),
		success: 'Email removed from Tracking'
	})
	return r !== null
}
