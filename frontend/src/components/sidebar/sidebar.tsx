import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Search,
  SlidersHorizontal,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Sun,
  Moon,
  Sparkles,
} from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { useTheme } from "@/components/theme-provider";
import { useThreads, useCreateThread } from "@/hooks/use-threads";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ThreadItem } from "@/components/sidebar/thread-item";
import { groupThreadsByDate } from "@/lib/utils";

export function Sidebar() {
  const [search, setSearch] = useState("");
  const [pinnedOnly, setPinnedOnly] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, fetchNextPage, hasNextPage } = useThreads(search || undefined);
  const createThread = useCreateThread();

  const allThreads = data?.pages.flatMap((p) => p.items) ?? [];
  const threads = pinnedOnly ? allThreads.filter((t) => t.pinned) : allThreads;
  const groups = groupThreadsByDate(threads);

  const handleNewChat = async () => {
    // Without this guard, a fast double-click fires two overlapping
    // mutations and silently creates two empty threads.
    if (createThread.isPending) return;
    const thread = await createThread.mutateAsync();
    navigate(`/chat/${thread.id}`);
  };

  const handleLogout = async () => {
    // Awaited so local tokens/user state are actually cleared before the
    // query cache is dropped and the redirect fires - otherwise those ran
    // immediately while `logout()`'s revoke call was still in flight, and a
    // fast re-render in between could briefly see stale "authenticated" state.
    await logout();
    queryClient.clear();
    navigate("/login");
  };

  if (collapsed) {
    return (
      <aside className="relative z-10 flex h-full w-16 flex-col items-center gap-3 border-r border-border bg-sidebar py-4">
        <div className="gradient-brand glow-primary flex h-9 w-9 items-center justify-center rounded-xl">
          <Sparkles className="h-4.5 w-4.5 text-white" />
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={() => setCollapsed(false)}
          aria-label="Expand sidebar"
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button
          size="icon"
          className="h-9 w-9 rounded-xl"
          onClick={handleNewChat}
          disabled={createThread.isPending}
          aria-label="New chat"
        >
          <Plus className="h-4 w-4" />
        </Button>
        <div className="mt-auto">
          <Avatar className="h-8 w-8">
            <AvatarImage src={user?.avatar_url || undefined} />
            <AvatarFallback className="gradient-brand text-xs text-white">
              {user?.username?.charAt(0).toUpperCase() || "U"}
            </AvatarFallback>
          </Avatar>
        </div>
      </aside>
    );
  }

  return (
    <aside className="relative z-10 flex h-full w-[19rem] flex-col border-r border-border bg-sidebar">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-4 pb-3 pt-4">
        <div className="gradient-brand glow-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-xl">
          <Sparkles className="h-4.5 w-4.5 text-white" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-bold leading-tight">Lumina AI</p>
          <p className="truncate text-xs text-muted-foreground">Your AI Assistant</p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={() => setCollapsed(true)}
          aria-label="Collapse sidebar"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
      </div>

      {/* New chat */}
      <div className="px-3 pb-3">
        <Button
          className="w-full justify-center gap-2"
          onClick={handleNewChat}
          disabled={createThread.isPending}
        >
          <Plus className="h-4 w-4" />
          New Chat
        </Button>
      </div>

      {/* Search */}
      <div className="flex items-center gap-2 px-3 pb-2">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search chats..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="border-transparent bg-accent/60 pl-8 focus-visible:border-border focus-visible:ring-0"
          />
        </div>
        <Button
          variant={pinnedOnly ? "secondary" : "ghost"}
          size="icon"
          className="h-10 w-10 shrink-0 border border-border"
          onClick={() => setPinnedOnly((v) => !v)}
          aria-label="Show pinned chats only"
          title="Show pinned chats only"
        >
          <SlidersHorizontal className="h-4 w-4" />
        </Button>
      </div>

      {/* Thread list, grouped by date */}
      <ScrollArea className="chat-scrollbar flex-1 px-3">
        {groups.map((group) => (
          <div key={group.label} className="mb-3">
            <p className="px-2 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {group.label}
            </p>
            <div className="space-y-0.5">
              {group.items.map((thread) => (
                <ThreadItem key={thread.id} thread={thread} />
              ))}
            </div>
          </div>
        ))}
        {hasNextPage && (
          <Button
            variant="ghost"
            size="sm"
            className="w-full text-xs text-muted-foreground"
            onClick={() => fetchNextPage()}
          >
            Load more
          </Button>
        )}
      </ScrollArea>

      {/* User footer */}
      <div className="border-t border-border p-3">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="flex w-full items-center gap-2 rounded-lg p-1.5 text-left hover:bg-accent">
              <Avatar className="h-9 w-9 shrink-0">
                <AvatarImage src={user?.avatar_url || undefined} />
                <AvatarFallback className="gradient-brand text-xs text-white">
                  {user?.username?.charAt(0).toUpperCase() || "U"}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{user?.username}</p>
                <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
              </div>
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem onSelect={() => navigate("/profile")}>Profile</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => navigate("/settings")}>Settings</DropdownMenuItem>
            <DropdownMenuItem onSelect={handleLogout}>Log out</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <div className="mt-2 grid grid-cols-3 gap-1">
          <button
            className="flex flex-col items-center gap-1 rounded-lg py-2 text-muted-foreground hover:bg-accent hover:text-foreground"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            <span className="text-[10px]">{theme === "dark" ? "Light" : "Dark"}</span>
          </button>
          <button
            className="flex flex-col items-center gap-1 rounded-lg py-2 text-muted-foreground hover:bg-accent hover:text-foreground"
            onClick={() => navigate("/settings")}
          >
            <Settings className="h-4 w-4" />
            <span className="text-[10px]">Settings</span>
          </button>
          <button
            className="flex flex-col items-center gap-1 rounded-lg py-2 text-muted-foreground hover:bg-accent hover:text-foreground"
            onClick={handleLogout}
          >
            <LogOut className="h-4 w-4" />
            <span className="text-[10px]">Logout</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
