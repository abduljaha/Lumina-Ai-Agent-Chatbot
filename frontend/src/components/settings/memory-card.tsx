import { Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useClearMemories, useDeleteMemory, useMemories } from "@/hooks/use-memories";

// Only the memory types a user would recognize as "things it remembers about
// me" (ChatGPT/Gemini's "Saved memories") are shown here. short_term/thread/
// summarization/semantic are working memory the agent uses internally, not
// facts a person would expect to review or delete one by one.
const VISIBLE_TYPES = new Set(["entity", "user_preference"]);

function formatMemoryLabel(content: string, memoryType: string): string {
  if (memoryType === "entity") {
    // Stored as "key: value" (e.g. "location: Hyderabad") - shown title-cased.
    const [key, ...rest] = content.split(":");
    const value = rest.join(":").trim();
    if (value) {
      return `${key.trim().replace(/_/g, " ")}: ${value}`;
    }
  }
  return content;
}

export function MemoryCard() {
  const { data, isLoading } = useMemories();
  const deleteMemory = useDeleteMemory();
  const clearMemories = useClearMemories();

  const memories = (data?.items ?? []).filter((m) => VISIBLE_TYPES.has(m.memory_type));

  const handleClearAll = () => {
    if (!window.confirm("Forget everything Lumina AI remembers about you? This can't be undone.")) {
      return;
    }
    clearMemories.mutate(undefined, {
      onSuccess: () => toast.success("Memory cleared"),
      onError: () => toast.error("Failed to clear memory"),
    });
  };

  const handleDelete = (id: string) => {
    deleteMemory.mutate(id, {
      onError: () => toast.error("Failed to delete memory"),
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Memory</CardTitle>
        <CardDescription>
          Facts and preferences Lumina AI has picked up from your conversations and uses to
          personalize replies across every chat - like ChatGPT and Gemini's memory features.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : memories.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing remembered yet. As you chat, durable facts you share (like your name or
            preferences) will show up here.
          </p>
        ) : (
          <ul className="space-y-2">
            {memories.map((memory) => (
              <li
                key={memory.id}
                className="glass-subtle flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm"
              >
                <span className="min-w-0 flex-1 truncate capitalize">
                  {formatMemoryLabel(memory.content, memory.memory_type)}
                </span>
                <button
                  onClick={() => handleDelete(memory.id)}
                  className="shrink-0 text-muted-foreground transition-colors hover:text-destructive"
                  aria-label="Forget this"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}

        {memories.length > 0 && (
          <div className="flex justify-end pt-1">
            <Button
              variant="outline"
              size="sm"
              className="gap-2 text-destructive hover:text-destructive"
              onClick={handleClearAll}
              disabled={clearMemories.isPending}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear all memory
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
