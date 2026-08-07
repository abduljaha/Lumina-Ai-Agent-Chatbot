import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ChevronDown, Share, Star, MoreHorizontal, Pencil, Trash2, Download } from "lucide-react";
import type { Message, Thread } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useDeleteThread, usePinThread, useRenameThread } from "@/hooks/use-threads";
import { cn } from "@/lib/utils";

interface ChatHeaderProps {
  thread: Thread | null | undefined;
  messages: Message[];
}

export function ChatHeader({ thread, messages }: ChatHeaderProps) {
  const navigate = useNavigate();
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(thread?.title ?? "");
  const renameThread = useRenameThread();
  const pinThread = usePinThread();
  const deleteThread = useDeleteThread();

  if (!thread) {
    return <div className="flex h-14 shrink-0 items-center border-b border-border px-4" />;
  }

  const handleRename = async () => {
    if (editValue.trim() && editValue !== thread.title) {
      await renameThread.mutateAsync({ threadId: thread.id, title: editValue.trim() });
    }
    setIsEditing(false);
  };

  const handleShare = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast.success("Link copied to clipboard");
    } catch {
      toast.error("Could not copy link");
    }
  };

  const handleTogglePin = () => {
    pinThread.mutate({ threadId: thread.id, pinned: !thread.pinned });
  };

  const handleExport = () => {
    const text = messages
      .map((m) => `${m.role === "user" ? "You" : "Assistant"}: ${m.content}`)
      .join("\n\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${thread.title || "chat"}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDelete = async () => {
    await deleteThread.mutateAsync(thread.id);
    navigate("/chat");
  };

  return (
    <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
      {isEditing ? (
        <Input
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={handleRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleRename();
            if (e.key === "Escape") setIsEditing(false);
          }}
          autoFocus
          className="h-8 max-w-xs"
        />
      ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm font-semibold hover:bg-accent">
              <span className="max-w-[240px] truncate">{thread.title}</span>
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-44">
            <DropdownMenuItem onSelect={() => setIsEditing(true)}>
              <Pencil className="mr-2 h-3.5 w-3.5" />
              Rename
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={handleTogglePin}>
              <Star className={cn("mr-2 h-3.5 w-3.5", thread.pinned && "fill-current text-primary")} />
              {thread.pinned ? "Unpin" : "Pin"}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={handleDelete} className="text-destructive focus:text-destructive">
              <Trash2 className="mr-2 h-3.5 w-3.5" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" className="gap-1.5" onClick={handleShare}>
          <Share className="h-3.5 w-3.5" />
          Share
        </Button>
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8"
          onClick={handleTogglePin}
          aria-label={thread.pinned ? "Unpin chat" : "Pin chat"}
        >
          <Star className={cn("h-4 w-4", thread.pinned && "fill-current text-primary")} />
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="icon" className="h-8 w-8" aria-label="More options">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem onSelect={handleExport} disabled={messages.length === 0}>
              <Download className="mr-2 h-3.5 w-3.5" />
              Export chat
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={handleDelete} className="text-destructive focus:text-destructive">
              <Trash2 className="mr-2 h-3.5 w-3.5" />
              Delete chat
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
