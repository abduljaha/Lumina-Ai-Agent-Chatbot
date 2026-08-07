import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { MessageSquare, Pin, Pencil, Trash2, MoreVertical } from "lucide-react";
import type { Thread } from "@/types";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useDeleteThread,
  usePinThread,
  useRenameThread,
} from "@/hooks/use-threads";
import { formatThreadTimestamp } from "@/lib/utils";

interface ThreadItemProps {
  thread: Thread;
}

export function ThreadItem({ thread }: ThreadItemProps) {
  const { threadId } = useParams();
  const navigate = useNavigate();
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(thread.title);
  const [menuOpen, setMenuOpen] = useState(false);

  const deleteThread = useDeleteThread();
  const renameThread = useRenameThread();
  const pinThread = usePinThread();

  const isActive = threadId === thread.id;

  const handleRename = async () => {
    if (editValue.trim() && editValue !== thread.title) {
      await renameThread.mutateAsync({ threadId: thread.id, title: editValue.trim() });
    }
    setIsEditing(false);
  };

  const handleDelete = async () => {
    await deleteThread.mutateAsync(thread.id);
    if (isActive) {
      navigate("/chat");
    }
  };

  return (
    <div
      className={cn(
        "group relative rounded-lg px-2 py-2 text-sm transition-colors hover:bg-accent",
        isActive && "border border-border bg-accent"
      )}
    >
      <div className="flex items-center gap-2">
        {thread.pinned ? (
          <Pin className="h-3.5 w-3.5 shrink-0 fill-current text-primary" />
        ) : (
          <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}

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
            className="h-6 px-1 text-sm"
          />
        ) : (
          <button
            className="min-w-0 flex-1 truncate text-left"
            onClick={() => navigate(`/chat/${thread.id}`)}
          >
            {thread.title}
          </button>
        )}

        {!isEditing && (
          <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100",
                  menuOpen && "opacity-100"
                )}
                onClick={(e) => e.stopPropagation()}
                aria-label="Thread options"
              >
                <MoreVertical className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuItem onSelect={() => setIsEditing(true)}>
                <Pencil className="mr-2 h-3.5 w-3.5" />
                Rename
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => pinThread.mutateAsync({ threadId: thread.id, pinned: !thread.pinned })}
              >
                <Pin className="mr-2 h-3.5 w-3.5" />
                {thread.pinned ? "Unpin" : "Pin"}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={handleDelete} className="text-destructive focus:text-destructive">
                <Trash2 className="mr-2 h-3.5 w-3.5" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {!isEditing && (
        <p className="mt-0.5 pl-5 text-[10px] text-muted-foreground">
          {formatThreadTimestamp(thread.updated_at)}
        </p>
      )}
    </div>
  );
}
