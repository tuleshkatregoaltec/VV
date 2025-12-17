import { stream } from './client';

export type StreamCallback = (chunk: string) => void;

export const chat = {
  sendPrompt: (prompt: string, onChunk: StreamCallback) =>
    stream(`/api/v1/chat/response?prompt=${encodeURIComponent(prompt)}`, onChunk),
};
