import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { ChatHeader } from "@/components/chat/chat-header";
import { useMessages, streamChat, regenerateChat, editChat } from "@/hooks/use-messages";
import { useCreateThread, useThread } from "@/hooks/use-threads";
import type { Message, StreamEvent } from "@/types";

const TOOL_ACTIVITY_LABELS: Record<string, string> = {
  weather: "Checking the weather",
  current_time: "Getting the time",
  calculator: "Calculating",
  web_search: "Searching the web",
  serp_search: "Getting live results",
  wikipedia: "Looking that up",
  knowledge_base_search: "Searching your documents",
};

function describeToolActivity(data: Record<string, unknown> | null | undefined): string {
  const results = Array.isArray(data) ? data : [];
  const labels = results
    .map((r) => TOOL_ACTIVITY_LABELS[(r as { tool?: string })?.tool ?? ""])
    .filter((label): label is string => Boolean(label));
  const unique = Array.from(new Set(labels));
  return unique.length ? unique.join(" & ") + "..." : "Working on it...";
}

export function ChatPage() {
  const { threadId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [localMessages, setLocalMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  // While regenerating, the target message's content is shown from here
  // instead of from `messages` - the server deletes the old row and
  // persists a brand-new one once done, so there's no stable id to patch
  // in place in the persisted list itself until that refetch lands.
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [regeneratingContent, setRegeneratingContent] = useState("");
  // While an edit is in flight: `targetId` is the message being edited,
  // `content` is its new text (shown immediately in place of the old text),
  // and everything after it in the merged view is hidden - the server is
  // about to delete those rows too, since they answered a prompt that no
  // longer exists once the edit lands.
  const [editState, setEditState] = useState<{
    targetId: string;
    content: string;
    assistantContent: string;
  } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const createThread = useCreateThread();

  // Bumped on every send and every thread switch. A stream's event
  // callbacks and its catch/finally block check this before touching state
  // - without it, a response still in flight when the user switches threads
  // (or fires a second send) keeps calling setState after the fact, and
  // those updates land on whatever thread happens to be showing *now*
  // rather than the one that was actually being replied to.
  const requestIdRef = useRef(0);
  // Sending the *first* message of a brand-new chat resolves a thread id
  // and navigates to it as part of the very same send - that threadId
  // change must NOT trigger the reset effect below, or it aborts the
  // request and wipes the optimistic messages that send just added. Real
  // thread switches (sidebar click, "New chat") never touch this flag, so
  // they still reset normally.
  const suppressNextResetRef = useRef(false);

  const { data } = useMessages(threadId);
  const messages = data?.pages.flatMap((p) => p.items) ?? [];
  const { data: currentThread } = useThread(threadId);

  // Switching threads (including to a brand-new, empty one) must drop any
  // leftover optimistic state and cancel whatever was still in flight
  // immediately - not "once the new thread's messages have loaded", which
  // left a stale reply from thread A visible on top of thread B for however
  // long B's fetch took, and let A's stream keep updating state neither
  // thread's view should have been affected by.
  useEffect(() => {
    if (suppressNextResetRef.current) {
      suppressNextResetRef.current = false;
      return;
    }
    abortRef.current?.abort();
    abortRef.current = null;
    requestIdRef.current += 1;
    setLocalMessages([]);
    setIsStreaming(false);
    setToolStatus(null);
    setRegeneratingId(null);
    setRegeneratingContent("");
    setEditState(null);
  }, [threadId]);

  // Cancel any in-flight request if the page itself unmounts (e.g.
  // navigating to Settings) - otherwise the fetch keeps running, its events
  // keep firing into a component that no longer exists, and the request
  // just wastes bandwidth/provider quota for a response nothing will ever
  // show.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // Shared by handleSend and ChatInput's document upload - a document
  // attached before the first message of a brand-new chat still needs a
  // real thread_id to be scoped to (see RAGRetrievalNode), not just
  // whatever thread the eventual first message happens to create.
  const ensureThreadId = useCallback(async (): Promise<string> => {
    if (threadId) return threadId;
    const thread = await createThread.mutateAsync();
    suppressNextResetRef.current = true;
    navigate(`/chat/${thread.id}`, { replace: true });
    return thread.id;
  }, [threadId, createThread, navigate]);

  const handleSend = useCallback(
    async (message: string, model?: string, images?: string[]) => {
      if (isStreaming) return;

      const currentThreadId = await ensureThreadId();

      const myRequestId = ++requestIdRef.current;
      const isCurrent = () => requestIdRef.current === myRequestId;

      setIsStreaming(true);
      setToolStatus(null);
      const controller = new AbortController();
      abortRef.current = controller;

      // Add user message optimistically
      const userMessage: Message = {
        id: `local-${Date.now()}`,
        thread_id: currentThreadId,
        role: "user",
        content: message,
        attachments: [],
        images: images ?? [],
        metadata_: {},
        created_at: new Date().toISOString(),
      };
      setLocalMessages((prev) => [...prev, userMessage]);

      // Add assistant placeholder
      const assistantMessage: Message = {
        id: `streaming-${Date.now()}`,
        thread_id: currentThreadId,
        role: "assistant",
        content: "",
        attachments: [],
        images: [],
        metadata_: {},
        created_at: new Date().toISOString(),
      };
      setLocalMessages((prev) => [...prev, assistantMessage]);

      let wasAborted = false;
      try {
        await streamChat(
          {
            thread_id: currentThreadId,
            message,
            model,
            images,
            stream: true,
          },
          (event: StreamEvent) => {
            if (!isCurrent()) return;
            if (event.type === "tool_call") {
              // Tool execution (weather/time/calculator lookups, ...) can take
              // several seconds with no "token" event in that window - without
              // this the assistant bubble just sits empty, which looks
              // indistinguishable from the app being frozen.
              setToolStatus(describeToolActivity(event.data));
            }
            // "message" carries the ask_user clarifying question down the same
            // streaming path as "token" - treated identically here, since it's
            // the actual visible reply for that turn, not a status update.
            if ((event.type === "token" || event.type === "message") && event.content) {
              setToolStatus(null);
              setLocalMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last?.role === "assistant") {
                  // Each event carries the full generation so far, not a delta:
                  // later nodes (reflection, formatting) can rewrite it wholesale.
                  // Appending would repeat the whole reply on every update.
                  next[next.length - 1] = { ...last, content: event.content ?? "" };
                }
                return next;
              });
            }
            if (event.type === "error") {
              setToolStatus(null);
              setLocalMessages((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last?.role === "assistant") {
                  next[next.length - 1] = {
                    ...last,
                    content: `⚠️ ${event.content || "An error occurred"}`,
                  };
                }
                return next;
              });
            }
          },
          controller.signal
        );
      } catch (error) {
        if (!isCurrent()) return;
        if ((error as Error).name === "AbortError") {
          wasAborted = true;
        } else {
          setToolStatus(null);
          setLocalMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "assistant") {
              next[next.length - 1] = {
                ...last,
                content: "⚠️ Failed to get response. Please try again.",
              };
            }
            return next;
          });
        }
      } finally {
        // Awaited (invalidateQueries resolves once the refetch for active
        // queries completes) so the persisted list is guaranteed to already
        // contain this exchange before the optimistic copies are dropped.
        // isStreaming/local-clear both wait for this SAME await and land
        // together - flipping isStreaming false any earlier reopens the
        // input before the persisted refetch lands, and a fast next action
        // (retry, another send) would then see both the stale local copy
        // *and* its freshly-fetched persisted duplicate at once, which is
        // exactly what was corrupting "find the last user message" for retry.
        await queryClient.invalidateQueries({ queryKey: ["messages", currentThreadId] });
        await queryClient.invalidateQueries({ queryKey: ["threads"] });
        if (isCurrent()) {
          setIsStreaming(false);
          setToolStatus(null);
          abortRef.current = null;
          // Skip on abort: the backend never got to persist an assistant
          // reply for a stopped generation, so clearing local state here
          // would erase the partial answer the user could still see and
          // replace it with nothing rather than leaving it visible.
          if (!wasAborted) {
            setLocalMessages([]);
          }
        }
      }
    },
    [threadId, isStreaming, createThread, navigate, queryClient]
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setToolStatus(null);
  }, []);

  const displayMessages = (() => {
    const base = [...localMessages, ...messages].map((m) =>
      m.id === regeneratingId ? { ...m, content: regeneratingContent } : m
    );
    if (!editState) return base;
    const idx = base.findIndex((m) => m.id === editState.targetId);
    if (idx === -1) return base;
    // Truncate to the edited message (with its new content) and append a
    // fresh assistant placeholder - mirrors what the server is doing
    // (delete everything after the edited message, then generate one new
    // reply), so the view doesn't show stale messages mid-edit.
    const truncated = base
      .slice(0, idx + 1)
      .map((m, i) => (i === idx ? { ...m, content: editState.content } : m));
    const assistantPlaceholder: Message = {
      id: `editing-${editState.targetId}`,
      thread_id: threadId ?? "",
      role: "assistant",
      content: editState.assistantContent,
      attachments: [],
      images: [],
      metadata_: {},
      created_at: new Date().toISOString(),
    };
    return [...truncated, assistantPlaceholder];
  })();

  const handleRegenerate = useCallback(
    async (messageId: string) => {
      if (!threadId) return;
      const myRequestId = ++requestIdRef.current;
      const isCurrent = () => requestIdRef.current === myRequestId;

      setIsStreaming(true);
      setToolStatus(null);
      setRegeneratingId(messageId);
      setRegeneratingContent("");
      const controller = new AbortController();
      abortRef.current = controller;

      let wasAborted = false;
      try {
        await regenerateChat(
          threadId,
          messageId,
          (event: StreamEvent) => {
            if (!isCurrent()) return;
            if (event.type === "tool_call") {
              setToolStatus(describeToolActivity(event.data));
            }
            if ((event.type === "token" || event.type === "message") && event.content) {
              setToolStatus(null);
              setRegeneratingContent(event.content ?? "");
            }
            if (event.type === "error") {
              setToolStatus(null);
              setRegeneratingContent(`⚠️ ${event.content || "An error occurred"}`);
            }
          },
          controller.signal
        );
      } catch (error) {
        if (!isCurrent()) return;
        if ((error as Error).name === "AbortError") {
          wasAborted = true;
        } else {
          setRegeneratingContent("⚠️ Failed to regenerate. Please try again.");
        }
      } finally {
        // Same reasoning as handleSend's finally: wait for the persisted
        // refetch before dropping the override, so the freshly-regenerated
        // (new id, since the old row was deleted server-side) message is
        // already in `messages` by the time `regeneratingId` stops matching
        // anything - no flicker back to the old content in between.
        await queryClient.invalidateQueries({ queryKey: ["messages", threadId] });
        await queryClient.invalidateQueries({ queryKey: ["threads"] });
        if (isCurrent()) {
          setIsStreaming(false);
          setToolStatus(null);
          abortRef.current = null;
          if (!wasAborted) {
            setRegeneratingId(null);
            setRegeneratingContent("");
          }
        }
      }
    },
    [threadId, queryClient]
  );

  const handleEdit = useCallback(
    async (messageId: string, newContent: string) => {
      if (!threadId || isStreaming) return;
      const myRequestId = ++requestIdRef.current;
      const isCurrent = () => requestIdRef.current === myRequestId;

      setIsStreaming(true);
      setToolStatus(null);
      setEditState({ targetId: messageId, content: newContent, assistantContent: "" });
      const controller = new AbortController();
      abortRef.current = controller;

      let wasAborted = false;
      try {
        await editChat(
          threadId,
          messageId,
          newContent,
          (event: StreamEvent) => {
            if (!isCurrent()) return;
            if (event.type === "tool_call") {
              setToolStatus(describeToolActivity(event.data));
            }
            if ((event.type === "token" || event.type === "message") && event.content) {
              setToolStatus(null);
              setEditState((prev) => (prev ? { ...prev, assistantContent: event.content ?? "" } : prev));
            }
            if (event.type === "error") {
              setToolStatus(null);
              setEditState((prev) =>
                prev ? { ...prev, assistantContent: `⚠️ ${event.content || "An error occurred"}` } : prev
              );
            }
          },
          controller.signal
        );
      } catch (error) {
        if (!isCurrent()) return;
        if ((error as Error).name === "AbortError") {
          wasAborted = true;
        } else {
          setEditState((prev) =>
            prev ? { ...prev, assistantContent: "⚠️ Failed to get response. Please try again." } : prev
          );
        }
      } finally {
        // Same reasoning as handleSend/handleRegenerate: wait for the
        // persisted refetch (now reflecting the edit + truncation) before
        // dropping the override, so there's no flicker back to pre-edit
        // content in between.
        await queryClient.invalidateQueries({ queryKey: ["messages", threadId] });
        await queryClient.invalidateQueries({ queryKey: ["threads"] });
        if (isCurrent()) {
          setIsStreaming(false);
          setToolStatus(null);
          abortRef.current = null;
          if (!wasAborted) {
            setEditState(null);
          }
        }
      }
    },
    [threadId, isStreaming, queryClient]
  );

  const handleRetry = useCallback(() => {
    // Regenerating mid-stream would race the in-flight request against a
    // new one over the same assistant slot - Stop first, then retry.
    if (isStreaming) return;
    // Searching the full merged view (not just localMessages, which empties
    // out as soon as the persisted list loads) is what makes retry keep
    // working for the rest of the conversation, not just the message
    // right after you land on a thread.
    const lastAssistant = [...displayMessages].reverse().find((m) => m.role === "assistant");
    const isPersisted = (id: string) => !id.startsWith("local-") && !id.startsWith("streaming-");
    if (lastAssistant && isPersisted(lastAssistant.id)) {
      // The normal, expected path: regenerate that exact reply in place.
      handleRegenerate(lastAssistant.id);
      return;
    }
    // Fallback for the rare case a persisted reply doesn't exist yet to
    // regenerate (e.g. retry clicked in the same tick as a prior send
    // hadn't settled) - resend as a fresh turn rather than doing nothing.
    const lastUser = [...displayMessages].reverse().find((m) => m.role === "user");
    if (lastUser) {
      setLocalMessages((prev) => prev.filter((m) => m.id !== lastUser.id));
      handleSend(lastUser.content, undefined, lastUser.images);
    }
  }, [displayMessages, isStreaming, handleSend, handleRegenerate]);

  return (
    <div className="flex h-full flex-col">
      {threadId && <ChatHeader thread={currentThread} messages={displayMessages} />}
      <div className="flex-1 overflow-hidden">
        <MessageList
          messages={displayMessages}
          isStreaming={isStreaming}
          toolStatus={toolStatus}
          onRetry={handleRetry}
          onEdit={handleEdit}
          onExampleSelect={handleSend}
        />
      </div>
      {/* Keyed by threadId so switching threads (or starting a new chat)
          always starts with a blank composer instead of carrying over
          whatever draft text was sitting unsent in the previous thread. */}
      <ChatInput
        key={threadId ?? "new"}
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
        ensureThreadId={ensureThreadId}
      />
    </div>
  );
}
