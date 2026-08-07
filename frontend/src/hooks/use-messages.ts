import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type { ChatRequest, ChatResponse, Message, StreamEvent } from "@/types";

interface MessageListResponse {
  items: Message[];
  total: number;
  has_more: boolean;
  next_cursor?: string | null;
}

export function useMessages(threadId: string | undefined) {
  return useInfiniteQuery({
    queryKey: ["messages", threadId],
    queryFn: async ({ pageParam }) => {
      if (!threadId) return { items: [], total: 0, has_more: false };
      const { data } = await api.get<MessageListResponse>(`/threads/${threadId}/messages`, {
        params: { offset: pageParam, limit: 50 },
      });
      return data;
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.items.length : undefined,
    enabled: Boolean(threadId),
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (
      payload: ChatRequest
    ): Promise<ChatResponse> => {
      const { data } = await api.post<ChatResponse>("/chat/messages", {
        ...payload,
        stream: false,
      });
      return data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["messages", data.thread_id] });
      queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}

export function useMessageFeedback() {
  return useMutation({
    mutationFn: async ({
      messageId,
      feedbackType,
    }: {
      messageId: string;
      feedbackType: "thumbs_up" | "thumbs_down";
    }) => {
      const { data } = await api.post(`/chat/messages/${messageId}/feedback`, {
        feedback_type: feedbackType,
      });
      return data;
    },
  });
}

async function postSSE(
  path: string,
  body: unknown,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8001/api/v1";
  const token = localStorage.getItem("access_token");

  const response = await fetch(`${apiUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`Stream failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const emitLine = (line: string) => {
    if (!line.startsWith("data: ")) return;
    try {
      onEvent(JSON.parse(line.slice(6)) as StreamEvent);
    } catch {
      // ignore malformed events
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n\n");
      buffer = lines.pop() || "";
      lines.forEach(emitLine);
    }
    // The server's final event (typically "done") isn't guaranteed to be
    // followed by a trailing "\n\n" before the connection closes - without
    // this, that last event sits in `buffer` and is silently dropped,
    // which left the UI stuck showing the streaming/"thinking" state
    // forever even though the backend had already finished.
    if (buffer.trim()) {
      emitLine(buffer);
    }
  } finally {
    reader.releaseLock();
  }
}

export async function streamChat(
  payload: ChatRequest,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  return postSSE("/chat/stream", { ...payload, stream: true }, onEvent, signal);
}

/** Regenerates a specific assistant reply in place (deletes + re-answers
 * the same turn server-side) rather than appending a brand-new exchange. */
export async function regenerateChat(
  threadId: string,
  messageId: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  return postSSE("/chat/regenerate/stream", { thread_id: threadId, message_id: messageId }, onEvent, signal);
}
