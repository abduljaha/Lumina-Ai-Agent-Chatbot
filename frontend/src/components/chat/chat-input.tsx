import { useState, useRef, useEffect } from "react";
import { Paperclip, Mic, Send, Square, Sparkles, Loader2, FileText, X, Globe, Image as ImageIcon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ModelSelector } from "@/components/chat/model-selector";
import { QuickActions } from "@/components/chat/quick-actions";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import type { DocumentInfo } from "@/types";

const ACCEPTED_DOCUMENT_TYPES =
  ".pdf,.docx,.pptx,.txt,.md,.csv,.xlsx,.xls,.json,.xml,.html,.htm,.py,.js,.ts,.java,.c,.cpp,.go,.rs,.rb,.php";
const ACCEPTED_IMAGE_TYPES = "image/png,image/jpeg,image/webp,image/gif";
// Vision APIs pay per image in tokens, and a chat request is already a
// single JSON body with no chunked upload - both stay reasonable at a
// handful of images rather than an unbounded attach list.
const MAX_IMAGES = 4;
const MAX_IMAGE_SIZE_MB = 8;

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

interface ChatInputProps {
  onSend: (message: string, model?: string, images?: string[]) => void;
  onStop?: () => void;
  isStreaming?: boolean;
  // Resolves to the current thread's id, creating one first if this is a
  // brand-new chat - so a document attached before the first message is
  // still scoped to the conversation it ends up in, not left unscoped.
  ensureThreadId: () => Promise<string>;
}

export function ChatInput({ onSend, onStop, isStreaming, ensureThreadId }: ChatInputProps) {
  const [message, setMessage] = useState("");
  const [model, setModel] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [attachedDoc, setAttachedDoc] = useState<DocumentInfo | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [attachedImages, setAttachedImages] = useState<string[]>([]);
  // One-shot modifiers: applied to the next message only, then reset -
  // matches how a "mode" toggle should feel (deliberate per-message choice,
  // not a sticky setting silently affecting messages the user forgot it was on for).
  const [webSearchMode, setWebSearchMode] = useState(false);
  const [detailedMode, setDetailedMode] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [message]);

  const handleSend = () => {
    if ((!message.trim() && attachedImages.length === 0) || isStreaming) return;
    let content = message.trim();
    // Prefixes chosen to land squarely on existing intent-detection patterns
    // (search/detail phrasing) rather than needing a new backend channel -
    // the assistant sees exactly what the user sees, nothing hidden.
    if (webSearchMode) content = `Search the web for the latest information: ${content}`;
    if (detailedMode) content = `Please give a thorough, detailed answer: ${content}`;
    // A bare image with no question is still a valid request ("what is
    // this?" is implied), but an empty message string reads as nothing to
    // send - give the backend something to route on.
    if (!content && attachedImages.length > 0) content = "What's in this image?";
    onSend(content, model || undefined, attachedImages.length ? attachedImages : undefined);
    setMessage("");
    setAttachedDoc(null);
    setAttachedImages([]);
    setWebSearchMode(false);
    setDetailedMode(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleVoice = () => {
    if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
      toast.error("Voice input isn't supported in this browser");
      return;
    }
    setIsRecording((prev) => !prev);
  };

  const handleAttachClick = () => {
    fileInputRef.current?.click();
  };

  const handleImageAttachClick = () => {
    imageInputRef.current?.click();
  };

  const handleImagesSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // allow re-selecting the same file later
    if (!files.length) return;

    const room = MAX_IMAGES - attachedImages.length;
    if (room <= 0) {
      toast.error(`You can attach up to ${MAX_IMAGES} images per message.`);
      return;
    }
    const accepted = files.slice(0, room);
    if (files.length > accepted.length) {
      toast.error(`Only the first ${accepted.length} image(s) were attached (max ${MAX_IMAGES}).`);
    }

    const dataUrls: string[] = [];
    for (const file of accepted) {
      if (file.size > MAX_IMAGE_SIZE_MB * 1024 * 1024) {
        toast.error(`"${file.name}" is over ${MAX_IMAGE_SIZE_MB}MB and was skipped.`);
        continue;
      }
      try {
        dataUrls.push(await fileToDataUrl(file));
      } catch {
        toast.error(`Couldn't read "${file.name}".`);
      }
    }
    if (dataUrls.length) {
      setAttachedImages((prev) => [...prev, ...dataUrls]);
    }
  };

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;

    setIsUploading(true);
    try {
      // Resolved first (creates the thread if this is a brand-new chat) so
      // the document is tied to this conversation from the moment it's
      // indexed - see RAGRetrievalNode, which uses this to make an upload
      // reliably answerable without the user re-naming the file.
      const threadId = await ensureThreadId();
      const formData = new FormData();
      formData.append("file", file);
      formData.append("thread_id", threadId);
      const { data } = await api.post<DocumentInfo>("/files/documents", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      if (data.status === "failed") {
        const reason = (data.metadata_?.error as string | undefined) ?? "processing failed";
        toast.error(`Couldn't index "${file.name}": ${reason}`);
      } else {
        setAttachedDoc(data);
        toast.success(`"${file.name}" is indexed - ask about it in this chat.`);
      }
    } catch (error) {
      const message =
        (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data
          ?.error?.message ?? "Upload failed.";
      toast.error(message);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="pb-4 pt-1">
      <QuickActions onSelect={(prompt) => { setMessage(prompt); textareaRef.current?.focus(); }} />

      <div className="mx-auto max-w-3xl px-4">
        <div className="mb-2 flex items-center gap-2">
          <ModelSelector value={model} onChange={setModel} />
        </div>

        {attachedDoc && (
          <div className="mb-2 flex w-fit items-center gap-2 rounded-lg border border-border bg-secondary px-3 py-1.5 text-xs">
            <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="max-w-[220px] truncate">{attachedDoc.filename}</span>
            <button
              type="button"
              onClick={() => setAttachedDoc(null)}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Dismiss attachment"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {attachedImages.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachedImages.map((src, i) => (
              <div key={i} className="group relative h-16 w-16 shrink-0 overflow-hidden rounded-lg border border-border">
                <img src={src} alt="Attached" className="h-full w-full object-cover" />
                <button
                  type="button"
                  onClick={() => setAttachedImages((prev) => prev.filter((_, idx) => idx !== i))}
                  className="absolute right-0.5 top-0.5 rounded-full bg-black/60 p-0.5 text-white opacity-0 transition-opacity group-hover:opacity-100"
                  aria-label="Remove image"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-end gap-1 rounded-3xl border border-border bg-card p-2 shadow-sm">
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_DOCUMENT_TYPES}
            className="hidden"
            onChange={handleFileSelected}
          />
          <input
            ref={imageInputRef}
            type="file"
            accept={ACCEPTED_IMAGE_TYPES}
            multiple
            className="hidden"
            onChange={handleImagesSelected}
          />
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0 rounded-full"
            onClick={handleAttachClick}
            disabled={isUploading}
            aria-label="Attach a document"
            title="Attach a document (indexed for search)"
          >
            {isUploading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Paperclip className="h-4 w-4" />
            )}
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className={cn("shrink-0 rounded-full", attachedImages.length > 0 && "bg-accent text-primary")}
            onClick={handleImageAttachClick}
            disabled={attachedImages.length >= MAX_IMAGES}
            aria-label="Attach an image"
            title="Attach an image to ask about"
          >
            <ImageIcon className="h-4 w-4" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className={cn("shrink-0 rounded-full", webSearchMode && "bg-accent text-primary")}
            onClick={() => setWebSearchMode((v) => !v)}
            aria-label="Search the web for this message"
            aria-pressed={webSearchMode}
            title="Search the web for this message"
          >
            <Globe className="h-4 w-4" />
          </Button>

          <Textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Lumina AI..."
            className="min-h-[40px] flex-1 resize-none border-0 bg-transparent focus-visible:ring-0"
            rows={1}
          />

          <Button
            variant="ghost"
            size="icon"
            className={cn("shrink-0 rounded-full", detailedMode && "bg-accent text-primary")}
            onClick={() => setDetailedMode((v) => !v)}
            aria-label="Ask for a more detailed answer"
            aria-pressed={detailedMode}
            title="Ask for a more detailed answer"
          >
            <Sparkles className="h-4 w-4" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className={cn("shrink-0 rounded-full", isRecording && "text-destructive")}
            onClick={handleVoice}
            aria-label={isRecording ? "Stop recording" : "Voice input"}
          >
            {isRecording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          </Button>

          {isStreaming ? (
            <Button size="icon" variant="secondary" className="shrink-0 rounded-full" onClick={onStop}>
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              size="icon"
              onClick={handleSend}
              disabled={!message.trim() && attachedImages.length === 0}
              className="shrink-0 rounded-full"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>

        <p className="mt-2 text-center text-xs text-muted-foreground">
          Lumina AI can make mistakes. Please check important information.
        </p>
      </div>
    </div>
  );
}
