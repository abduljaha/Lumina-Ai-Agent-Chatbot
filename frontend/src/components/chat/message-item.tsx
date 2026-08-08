import { memo, useState } from "react";
import {
  Bot,
  Copy,
  Check,
  ThumbsUp,
  ThumbsDown,
  RefreshCw,
  Volume2,
  Square,
  CheckCheck,
  Pencil,
} from "lucide-react";
import { toast } from "sonner";
import type { Message } from "@/types";
import { MarkdownRenderer } from "@/components/chat/markdown-renderer";
import { ImageLightbox } from "@/components/chat/image-lightbox";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/utils";
import { useMessageFeedback } from "@/hooks/use-messages";

interface MessageItemProps {
  message: Message;
  isStreaming?: boolean;
  toolStatus?: string | null;
  onRetry?: () => void;
  // Only meaningful for a persisted user message - editing re-sends the
  // edited content and truncates everything after it server-side, so it
  // needs a real message_id to target (see chat.tsx's handleEdit).
  onEdit?: (messageId: string, newContent: string) => void;
}

export const MessageItem = memo(function MessageItem({
  message,
  isStreaming,
  toolStatus,
  onRetry,
  onEdit,
}: MessageItemProps) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [reaction, setReaction] = useState<"thumbs_up" | "thumbs_down" | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(message.content);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const feedback = useMessageFeedback();

  const isPersisted = !message.id.startsWith("local-") && !message.id.startsWith("streaming-");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy to clipboard");
    }
  };

  const handleSpeak = () => {
    if (!("speechSynthesis" in window)) {
      toast.error("Text-to-speech isn't supported in this browser");
      return;
    }
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(message.content);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    window.speechSynthesis.speak(utterance);
  };

  const handleReaction = (type: "thumbs_up" | "thumbs_down") => {
    if (feedback.isPending) return;
    setReaction(type);
    feedback.mutate(
      { messageId: message.id, feedbackType: type },
      {
        onError: () => {
          setReaction(null);
          toast.error("Could not submit feedback");
        },
      }
    );
  };

  const startEdit = () => {
    setEditValue(message.content);
    setIsEditing(true);
  };

  const cancelEdit = () => {
    setIsEditing(false);
    setEditValue(message.content);
  };

  const saveEdit = () => {
    const trimmed = editValue.trim();
    if (!trimmed || trimmed === message.content) {
      cancelEdit();
      return;
    }
    onEdit?.(message.id, trimmed);
    setIsEditing(false);
  };

  const handleEditKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      saveEdit();
    } else if (e.key === "Escape") {
      cancelEdit();
    }
  };

  return (
    <div className={cn("flex gap-3 py-4", isUser && "justify-end")}>
      {!isUser && (
        <Avatar className="h-8 w-8 shrink-0 ring-2 ring-border">
          <AvatarFallback className="gradient-brand text-white">
            <Bot className="h-4 w-4" />
          </AvatarFallback>
        </Avatar>
      )}

      <div className={cn("flex max-w-[80%] flex-col gap-1", isUser && "items-end")}>
        {isUser && message.images.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1.5">
            {message.images.map((src, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setLightboxIndex(i)}
                className="h-28 w-28 shrink-0 cursor-zoom-in overflow-hidden rounded-xl border border-border transition-opacity hover:opacity-90"
                aria-label={`Open image ${i + 1} of ${message.images.length}`}
              >
                <img src={src} alt="Attached" className="h-full w-full object-cover" />
              </button>
            ))}
          </div>
        )}
        {isUser && lightboxIndex !== null && (
          <ImageLightbox
            src={message.images[lightboxIndex]}
            alt={`Attached image ${lightboxIndex + 1}`}
            open={lightboxIndex !== null}
            onOpenChange={(open) => {
              if (!open) setLightboxIndex(null);
            }}
          />
        )}

        {isEditing ? (
          <div className="w-full min-w-[280px] rounded-2xl border border-border bg-card p-2">
            <Textarea
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onKeyDown={handleEditKeyDown}
              autoFocus
              className="min-h-[60px] resize-none border-0 bg-transparent text-sm focus-visible:ring-0"
            />
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" size="sm" className="h-7" onClick={cancelEdit}>
                Cancel
              </Button>
              <Button size="sm" className="h-7" onClick={saveEdit} disabled={!editValue.trim()}>
                Save &amp; submit
              </Button>
            </div>
          </div>
        ) : (
          <div
            className={cn(
              "rounded-2xl px-4 py-2.5",
              isUser ? "gradient-brand glow-primary text-white" : "border border-border bg-card text-card-foreground"
            )}
          >
            {isUser ? (
              <p className="whitespace-pre-wrap text-sm">{message.content}</p>
            ) : !message.content && isStreaming ? (
              <ThinkingIndicator label={toolStatus} />
            ) : (
              <MarkdownRenderer content={message.content} />
            )}
          </div>
        )}

        {/* Actions */}
        {!isEditing && isUser && (
          <div className="flex items-center gap-1 text-muted-foreground">
            <span className="mr-1 text-xs">{formatTime(message.created_at)}</span>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={handleCopy}
              aria-label="Copy message"
            >
              {copied ? <Check className="h-3 w-3 text-primary" /> : <Copy className="h-3 w-3" />}
            </Button>
            {onEdit && isPersisted && !isStreaming && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={startEdit}
                aria-label="Edit message"
              >
                <Pencil className="h-3 w-3" />
              </Button>
            )}
            <CheckCheck className="h-3.5 w-3.5 text-primary" />
          </div>
        )}
        {!isEditing && !isUser && (
          <div className="flex items-center gap-1 text-muted-foreground">
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={handleCopy}
              aria-label="Copy message"
            >
              {copied ? <Check className="h-3 w-3 text-primary" /> : <Copy className="h-3 w-3" />}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => handleReaction("thumbs_up")}
              aria-label="Good response"
            >
              <ThumbsUp className={cn("h-3 w-3", reaction === "thumbs_up" && "fill-current text-primary")} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => handleReaction("thumbs_down")}
              aria-label="Bad response"
            >
              <ThumbsDown className={cn("h-3 w-3", reaction === "thumbs_down" && "fill-current text-primary")} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={handleSpeak}
              aria-label={speaking ? "Stop reading aloud" : "Read aloud"}
            >
              {speaking ? <Square className="h-3 w-3" /> : <Volume2 className="h-3 w-3" />}
            </Button>
            {onRetry && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={onRetry}
                aria-label="Regenerate response"
              >
                <RefreshCw className="h-3 w-3" />
              </Button>
            )}
            <span className="ml-2 text-xs">{formatTime(message.created_at)}</span>
          </div>
        )}
      </div>
    </div>
  );
});

function ThinkingIndicator({ label }: { label?: string | null }) {
  return (
    <div className="flex items-center gap-2 py-0.5 text-sm text-muted-foreground">
      <span className="flex gap-1">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.3s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.15s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current" />
      </span>
      {label && <span>{label}</span>}
    </div>
  );
}
