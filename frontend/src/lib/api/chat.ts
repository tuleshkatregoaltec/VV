import { http, stream } from './client';
import type { StreamCallback } from './client';

export interface Conversation {
  id: number;
  user_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: string;
  content: string;
  created_at: string;
  tool_call_ids: number[] | null;
}

export interface CreateConversationRequest {
  title?: string;
}

export const chat = {
	createConversation: (data: CreateConversationRequest = {}) =>
		http.post<Conversation>('/api/v1/chat/conversations', data),

	getConversations: () =>
		http.get<{ conversations: Conversation[]; total: number }>('/api/v1/chat/conversations'),

	getMessages: (conversationId: number) =>
		http.get<Message[]>(`/api/v1/chat/conversations/${conversationId}/messages`),

	/** Streams AI response chunks via Server-Sent Events */
	sendMessage: (conversationId: number, message: string, onChunk: StreamCallback) =>
		stream(
			`/api/v1/chat/conversations/${conversationId}/messages/stream?message=${encodeURIComponent(message)}`,
			onChunk
		)
};
