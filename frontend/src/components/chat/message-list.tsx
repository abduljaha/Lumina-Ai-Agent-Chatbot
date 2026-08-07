import { useEffect, useMemo, useRef } from "react";
import { Cloud, Clock, Calculator, Newspaper, BookOpen, Code2, type LucideIcon } from "lucide-react";
import type { Message } from "@/types";
import { MessageItem } from "@/components/chat/message-item";
import { ScrollArea } from "@/components/ui/scroll-area";

interface MessageListProps {
  messages: Message[];
  isStreaming?: boolean;
  toolStatus?: string | null;
  onRetry?: () => void;
  onExampleSelect?: (message: string) => void;
}

export function MessageList({
  messages,
  isStreaming,
  toolStatus,
  onRetry,
  onExampleSelect,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Smooth-scroll once per message, but jump instantly for the token-by-
    // token updates during streaming - stacking dozens of smooth-scroll
    // animations per second is what made the view feel laggy while a reply
    // was still generating.
    bottomRef.current?.scrollIntoView({ behavior: isStreaming ? "auto" : "smooth" });
  }, [messages, isStreaming]);

  return (
    <ScrollArea className="h-full">
      <div className="mx-auto max-w-3xl px-4 py-6">
        {messages.length === 0 && !isStreaming ? (
          <EmptyState onExampleSelect={onExampleSelect} />
        ) : (
          messages.map((message, index) => {
            const isLast = index === messages.length - 1;
            return (
              <MessageItem
                key={message.id}
                message={message}
                isStreaming={isStreaming}
                // Only the last message is the one currently being generated -
                // status text on earlier ones would be stale and misleading.
                toolStatus={isLast ? toolStatus : null}
                // Regenerate only makes sense for the most recent reply -
                // showing it on every past assistant message invited
                // clicking retry on an old message and having it silently
                // regenerate a completely different (the newest) one.
                onRetry={isLast && message.role === "assistant" ? onRetry : undefined}
              />
            );
          })
        )}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}

interface ExamplePrompt {
  icon: LucideIcon;
  label: string;
  prompt: string;
}

// A larger pool than shown at once, so a fresh chat surfaces a different
// mix of tools each time rather than the same four examples forever -
// covers every live-data tool the backend actually has registered
// (weather, current_time, calculator, web/serp_search, wikipedia,
// python_executor), not just a couple of them.
const EXAMPLE_POOL: ExamplePrompt[] = [
  { icon: Cloud, label: "Weather", prompt: "What's the weather right now in Tokyo?" },
  { icon: Cloud, label: "Weather", prompt: "Is it raining in London today?" },
  { icon: Clock, label: "Time", prompt: "What time is it in New York right now?" },
  { icon: Clock, label: "Time", prompt: "What's the current time in Sydney?" },
  { icon: Calculator, label: "Calculator", prompt: "Calculate an 18% tip on a $126.40 bill" },
  { icon: Calculator, label: "Calculator", prompt: "What is 4572 divided by 37?" },
  { icon: Newspaper, label: "Live info", prompt: "What's the latest news in AI today?" },
  { icon: Newspaper, label: "Live info", prompt: "What's the current price of gold?" },
  { icon: BookOpen, label: "Lookup", prompt: "Who is Ada Lovelace?" },
  { icon: Code2, label: "Code", prompt: "Write and run Python code to check if 97 is a prime number" },
];

function pickExamples(count: number): ExamplePrompt[] {
  const shuffled = [...EXAMPLE_POOL].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, count);
}

function EmptyState({ onExampleSelect }: { onExampleSelect?: (message: string) => void }) {
  // Recomputed once per mount (i.e. once per fresh empty chat), not on
  // every render - a stable set for the lifetime of this screen instead of
  // reshuffling out from under the user on an unrelated re-render.
  const examples = useMemo(() => pickExamples(4), []);

  return (
    <div className="flex h-full flex-col items-center justify-center py-20 text-center">
      <div className="gradient-brand glow-primary mb-4 rounded-full p-3">
        <svg
          className="h-7 w-7 text-brand-foreground"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
          />
        </svg>
      </div>
      <h2 className="text-2xl font-semibold text-foreground">
        How can I help you today?
      </h2>
      {onExampleSelect && (
        <>
          <p className="mt-2 text-sm text-muted-foreground">
            Try a live-data question - I can check the weather, the time, do
            calculations, and search the web in real time.
          </p>
          <div className="mt-6 grid w-full max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
            {examples.map((example) => (
              <button
                key={example.prompt}
                type="button"
                onClick={() => onExampleSelect(example.prompt)}
                className="flex items-start gap-3 rounded-xl border border-border bg-secondary/50 p-3 text-left transition-colors hover:bg-accent"
              >
                <example.icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                <div>
                  <div className="text-xs font-medium text-muted-foreground">{example.label}</div>
                  <div className="text-sm text-foreground">{example.prompt}</div>
                </div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
