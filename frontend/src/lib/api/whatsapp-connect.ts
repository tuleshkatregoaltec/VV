import { ApiError, client } from './client'

const base = '/api/v1/whatsapp'

export type ConnectionState = 'not_configured' | 'not_connected' | 'connected' | 'disconnected'
export type AutomationPausedReason = 'assistant_disabled' | 'intake_disabled'
export type CanSendMessage = 'AVAILABLE' | 'LIMITED' | 'BLOCKED'

export interface SignupConfig {
	configured: boolean
	missing: string[]
	app_id: string | null
	config_id: string | null
	graph_api_version: string
	extras: Record<string, unknown>
	state: string | null
}

export interface ContactsSummary {
	total: number
	blocked: number
	sync_requested_at: string | null
	synced_at: string | null
}

export interface AgentConnectionStatus {
	state: ConnectionState
	signup_configured: boolean
	connection_id: string | null
	phone_number_id: string | null
	waba_id: string | null
	business_id: string | null
	display_phone_number: string | null
	display_name: string | null
	onboarding_type: string | null
	automation_enabled: boolean
	/** True only when the switch is on, the number is connected and the server has replies on. */
	automation_active: boolean
	automation_paused_reason: AutomationPausedReason | null
	connected_at: string | null
	disconnected_at: string | null
	last_account_event: string | null
	quality_rating: string | null
	can_send_message: CanSendMessage | null
	health_errors: unknown[]
	payment_method_status: string
	contacts: ContactsSummary
}

export interface SignupCompleteBody {
	state: string
	code: string
	phone_number_id: string
	waba_id: string
	business_id?: string | null
	event: string
}

export interface SyncedContact {
	id: string
	wa_id: string
	name: string | null
	in_address_book: boolean
	blocked: boolean
	blocked_at: string | null
	updated_at: string
}

export interface ContactsPage {
	items: SyncedContact[]
	total: number
	limit: number
	offset: number
}

export interface ContactsParams {
	search?: string
	blocked?: boolean
	limit?: number
	offset?: number
}

export interface BlockBody {
	contact_ids?: string[]
	phone_numbers?: string[]
	blocked: boolean
}

export interface AdminConnectionRow {
	connection_id: string
	user_id: string
	user_email: string | null
	organization_id: string | null
	organization_name: string | null
	phone_number_id: string
	display_phone_number: string | null
	display_name: string | null
	status: string
	onboarding_type: string | null
	automation_enabled: boolean
	/** True only when the switch is on, the number is connected and the server has replies on. */
	automation_active: boolean
	automation_paused_reason: AutomationPausedReason | null
	contacts_total: number
	contacts_blocked: number
	contacts_synced_at: string | null
	last_message_at: string | null
	connected_at: string | null
	disconnected_at: string | null
	can_send_message: CanSendMessage | null
}

export interface AdminConnections {
	total: number
	connected: number
	automation_on: number
	automation_paused: number
	items: AdminConnectionRow[]
}

export const whatsappConnect = {
	signupConfig: () => client.get<SignupConfig>(`${base}/signup/config`),
	complete: (body: SignupCompleteBody) =>
		client.post<AgentConnectionStatus, SignupCompleteBody>(`${base}/signup/complete`, body),
	/** The backend answers 404 when the agent has no connected number; that is a normal state. */
	status: async (): Promise<AgentConnectionStatus | null> => {
		try {
			return await client.get<AgentConnectionStatus>(`${base}/connection`)
		} catch (error) {
			if (error instanceof ApiError && error.status === 404) return null
			throw error
		}
	},
	setAutomation: (enabled: boolean) =>
		client.patch<AgentConnectionStatus, { enabled: boolean }>(`${base}/connection/automation`, {
			enabled
		}),
	disconnect: () => client.post<AgentConnectionStatus>(`${base}/connection/disconnect`, undefined),
	contacts: (params: ContactsParams) =>
		client.get<ContactsPage>(
			client.withQuery(`${base}/connection/contacts`, {
				search: params.search || undefined,
				blocked: params.blocked,
				limit: params.limit,
				offset: params.offset
			})
		),
	setBlocked: (body: BlockBody) =>
		client.put<{ updated: number; blocked_total: number }, BlockBody>(
			`${base}/connection/contacts/blocked`,
			body
		),
	retrySync: () =>
		client.post<AgentConnectionStatus>(`${base}/connection/contacts/sync`, undefined),
	adminConnections: () => client.get<AdminConnections>('/api/v1/admin/whatsapp/connections')
}
