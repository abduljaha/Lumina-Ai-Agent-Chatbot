import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Moon, Sun, Monitor } from "lucide-react";
import { Link } from "react-router-dom";
import api from "@/lib/api";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { MemoryCard } from "@/components/settings/memory-card";
import { cn } from "@/lib/utils";

const SYSTEM_PROMPT_MAX_LENGTH = 4000;

interface UserSettings {
  theme: string;
  streaming_enabled: boolean;
  default_model?: string;
  default_provider?: string;
  voice_input_enabled?: boolean;
  voice_output_enabled?: boolean;
  system_prompt?: string;
}

export function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const queryClient = useQueryClient();
  const [streaming, setStreaming] = useState(true);
  const [systemPrompt, setSystemPrompt] = useState("");

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: async () => {
      const { data } = await api.get<UserSettings>("/users/me/settings");
      return data;
    },
  });

  useEffect(() => {
    if (settings?.system_prompt !== undefined) {
      setSystemPrompt(settings.system_prompt);
    }
  }, [settings?.system_prompt]);

  const updateSettings = useMutation({
    mutationFn: async (updates: Partial<UserSettings>) => {
      const { data } = await api.patch("/users/me/settings", updates);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Settings updated");
    },
    onError: () => {
      toast.error("Failed to update settings");
    },
  });

  const themeOptions = [
    { key: "light", label: "Light", icon: Sun },
    { key: "dark", label: "Dark", icon: Moon },
    { key: "system", label: "System", icon: Monitor },
  ] as const;

  return (
    <div className="relative z-10 mx-auto h-full max-w-2xl overflow-y-auto p-6">
      <div className="mb-6 flex items-center gap-4">
        <Button variant="ghost" size="icon" asChild>
          <Link to="/">
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <h1 className="text-2xl font-semibold">Settings</h1>
      </div>

      <div className="space-y-6">
        {/* Theme */}
        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
            <CardDescription>Customize how Lumina AI looks</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2">
              {themeOptions.map((option) => (
                <Button
                  key={option.key}
                  variant={theme === option.key ? "default" : "outline"}
                  className="gap-2"
                  onClick={() => {
                    setTheme(option.key);
                    updateSettings.mutate({ theme: option.key });
                  }}
                >
                  <option.icon className="h-4 w-4" />
                  {option.label}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Streaming */}
        <Card>
          <CardHeader>
            <CardTitle>Streaming</CardTitle>
            <CardDescription>Stream responses token by token</CardDescription>
          </CardHeader>
          <CardContent>
            <button
              onClick={() => {
                setStreaming(!streaming);
                updateSettings.mutate({ streaming_enabled: !streaming });
              }}
              className={cn(
                "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
                streaming ? "bg-primary" : "bg-muted"
              )}
            >
              <span
                className={cn(
                  "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
                  streaming ? "translate-x-6" : "translate-x-1"
                )}
              />
            </button>
          </CardContent>
        </Card>

        {/* System Prompt */}
        <Card>
          <CardHeader>
            <CardTitle>System Prompt</CardTitle>
            <CardDescription>
              Custom instructions Lumina AI follows in every conversation - tone, persona, format, anything you want it to always keep in mind.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value.slice(0, SYSTEM_PROMPT_MAX_LENGTH))}
              placeholder="e.g. Always answer concisely. Prefer bullet points. Explain code in Python unless asked otherwise."
              className="glass-subtle min-h-[120px]"
              maxLength={SYSTEM_PROMPT_MAX_LENGTH}
            />
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {systemPrompt.length}/{SYSTEM_PROMPT_MAX_LENGTH}
              </span>
              <Button
                size="sm"
                disabled={systemPrompt === (settings?.system_prompt ?? "") || updateSettings.isPending}
                onClick={() => updateSettings.mutate({ system_prompt: systemPrompt })}
              >
                {updateSettings.isPending ? "Saving..." : "Save"}
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Memory */}
        <MemoryCard />

        {/* Voice */}
        <Card>
          <CardHeader>
            <CardTitle>Voice & Audio</CardTitle>
            <CardDescription>Configure voice input and output preferences</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Voice Input</p>
                <p className="text-sm text-muted-foreground">Use your microphone to chat</p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  updateSettings.mutate({
                    voice_input_enabled: !settings?.voice_input_enabled,
                  })
                }
              >
                {settings?.voice_input_enabled ? "Enabled" : "Disabled"}
              </Button>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Voice Output</p>
                <p className="text-sm text-muted-foreground">Read responses aloud</p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  updateSettings.mutate({
                    voice_output_enabled: !settings?.voice_output_enabled,
                  })
                }
              >
                {settings?.voice_output_enabled ? "Enabled" : "Disabled"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
