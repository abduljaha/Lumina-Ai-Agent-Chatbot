import { Zap, FileText, MessageCircle, Code2, MoreHorizontal } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface QuickActionsProps {
  onSelect: (prompt: string) => void;
}

const QUICK_PROMPTS = [
  "Help me brainstorm ideas for...",
  "Write a professional email about...",
  "Explain this concept to me simply:",
  "Give me a step-by-step plan for...",
];

const MORE_ACTIONS = [
  { label: "Translate", prompt: "Translate the following to English:\n\n" },
  { label: "Fix grammar", prompt: "Fix the grammar and spelling in the following text:\n\n" },
  { label: "Brainstorm", prompt: "Help me brainstorm ideas about " },
];

export function QuickActions({ onSelect }: QuickActionsProps) {
  return (
    <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-2 px-4 pb-2">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className="flex items-center gap-1.5 rounded-full border border-border bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground hover:bg-accent">
            <Zap className="h-3.5 w-3.5" />
            Quick Prompt
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          {QUICK_PROMPTS.map((prompt) => (
            <DropdownMenuItem key={prompt} onSelect={() => onSelect(prompt)}>
              {prompt}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <button
        className="flex items-center gap-1.5 rounded-full border border-border bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground hover:bg-accent"
        onClick={() => onSelect("Please summarize this conversation so far.")}
      >
        <FileText className="h-3.5 w-3.5" />
        Summarize
      </button>

      <button
        className="flex items-center gap-1.5 rounded-full border border-border bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground hover:bg-accent"
        onClick={() => onSelect("Can you explain that in simpler terms?")}
      >
        <MessageCircle className="h-3.5 w-3.5" />
        Explain
      </button>

      <button
        className="flex items-center gap-1.5 rounded-full border border-border bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground hover:bg-accent"
        onClick={() => onSelect("Write code that does the following:\n\n")}
      >
        <Code2 className="h-3.5 w-3.5" />
        Code
      </button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className="flex items-center gap-1.5 rounded-full border border-border bg-secondary px-3 py-1.5 text-xs font-medium text-secondary-foreground hover:bg-accent">
            <MoreHorizontal className="h-3.5 w-3.5" />
            More
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-48">
          {MORE_ACTIONS.map((action) => (
            <DropdownMenuItem key={action.label} onSelect={() => onSelect(action.prompt)}>
              {action.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
