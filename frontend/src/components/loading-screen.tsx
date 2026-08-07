import { Loader2 } from "lucide-react";

export function LoadingScreen() {
  return (
    <div className="relative z-10 flex min-h-screen items-center justify-center">
      <div className="glass flex flex-col items-center gap-4 rounded-2xl px-8 py-6">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    </div>
  );
}
