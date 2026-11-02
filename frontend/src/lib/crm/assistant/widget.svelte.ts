/**
 * The floating assistant's state. Module level, so the open chat survives moving between CRM
 * pages (and the visit to the full Assistant page, where the widget is hidden).
 */
class AssistantWidget {
	open = $state(false)
	expanded = $state(false)
	conversationId = $state<number | null>(null)
}

export const widget = new AssistantWidget()
