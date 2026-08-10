import { useState } from "react";
import { Sparkles, Loader2, AlertCircle, Calculator, Clock, CloudSun, BookOpen, Terminal, Wand2 } from "lucide-react";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import type { AiTool } from "@/types";

const TOOL_ICONS: Record<string, typeof Calculator> = {
  calculator: Calculator,
  current_time: Clock,
  weather: CloudSun,
  wikipedia: BookOpen,
  python_executor: Terminal,
};

interface AiToolsMenuProps {
  onSelectTool: (examplePrompt: string) => void;
  detailedMode: boolean;
  onToggleDetailedMode: () => void;
}

/** The sparkles "AI tools" button: a popover, fetched live from the backend's tool
 * registry (GET /tools), that shows what the assistant can do and lets the user drop
 * a working example prompt into the input - plus the one-shot "detailed answer" mode. */
export function AiToolsMenu({ onSelectTool, detailedMode, onToggleDetailedMode }: AiToolsMenuProps) {
  const [tools, setTools] = useState<AiTool[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleOpenChange = async (open: boolean) => {
    if (!open || tools !== null || isLoading) return;
    setIsLoading(true);
    setError(null);
    try {
      const { data } = await api.get<{ items: AiTool[] }>("/tools");
      setTools(data.items);
    } catch {
      setError("Couldn't load tools.");
      toast.error("Couldn't load the tools list. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <DropdownMenu onOpenChange={handleOpenChange}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn("shrink-0 rounded-full", detailedMode && "bg-accent text-primary")}
          aria-label="AI tools"
          title="AI tools"
        >
          <Sparkles className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuCheckboxItem checked={detailedMode} onSelect={(e) => { e.preventDefault(); onToggleDetailedMode(); }}>
          <Wand2 className="mr-2 h-3.5 w-3.5 shrink-0" />
          <div className="flex flex-col">
            <span>Detailed answer</span>
            <span className="text-xs text-muted-foreground">Ask for a longer, more thorough response</span>
          </div>
        </DropdownMenuCheckboxItem>

        <DropdownMenuSeparator />

        {isLoading && (
          <div className="flex items-center justify-center gap-2 px-2 py-3 text-sm text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading tools...
          </div>
        )}

        {error && !isLoading && (
          <div className="flex items-center gap-2 px-2 py-3 text-sm text-destructive">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {error}
          </div>
        )}

        {!isLoading && !error && tools?.map((tool) => {
          const Icon = TOOL_ICONS[tool.name] ?? Sparkles;
          return (
            <DropdownMenuItem
              key={tool.name}
              onSelect={() => onSelectTool(tool.example_prompt)}
              disabled={!tool.example_prompt}
            >
              <Icon className="mr-2 h-3.5 w-3.5 shrink-0" />
              <div className="flex flex-col">
                <span className="capitalize">{tool.name.replace(/_/g, " ")}</span>
                <span className="line-clamp-1 text-xs text-muted-foreground">{tool.description}</span>
              </div>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
