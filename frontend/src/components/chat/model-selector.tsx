import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";
import api from "@/lib/api";
import type { ModelList } from "@/types";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface ModelSelectorProps {
  value: string;
  onChange: (value: string) => void;
}

export function ModelSelector({ value, onChange }: ModelSelectorProps) {
  const { data } = useQuery({
    queryKey: ["models"],
    queryFn: async () => {
      const { data } = await api.get<ModelList>("/models");
      return data;
    },
  });

  const selectedModel = data?.models.find((m) => m.name === value);
  const displayName = selectedModel?.display_name || value || "Select model";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-1">
          <span className="max-w-[140px] truncate">{displayName}</span>
          <ChevronDown className="h-3 w-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {data?.models.map((model) => (
          <DropdownMenuItem
            key={`${model.provider}-${model.name}`}
            onSelect={() => onChange(model.name)}
            className="flex items-center justify-between"
          >
            <div className="flex flex-col">
              <span className="text-sm">{model.display_name}</span>
              <span className="text-xs text-muted-foreground">{model.provider}</span>
            </div>
            {value === model.name && <Check className="h-4 w-4" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
