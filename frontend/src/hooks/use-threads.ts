import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type { Thread } from "@/types";

interface ThreadListResponse {
  items: Thread[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
}

export function useThreads(search?: string) {
  return useInfiniteQuery({
    queryKey: ["threads", search],
    queryFn: async ({ pageParam }) => {
      const { data } = await api.get<ThreadListResponse>("/threads", {
        params: { page: pageParam, page_size: 20, search },
      });
      return data;
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.page + 1 : undefined,
  });
}

export function useThread(threadId: string | undefined) {
  return useQuery({
    queryKey: ["thread", threadId],
    queryFn: async () => {
      if (!threadId) return null;
      const { data } = await api.get<Thread>(`/threads/${threadId}`);
      return data;
    },
    enabled: Boolean(threadId),
  });
}

export function useCreateThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<Thread>("/threads", { title: "New Chat" });
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}

export function useRenameThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ threadId, title }: { threadId: string; title: string }) => {
      const { data } = await api.patch<Thread>(`/threads/${threadId}`, { title });
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}

export function useDeleteThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (threadId: string) => {
      await api.delete(`/threads/${threadId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}

export function usePinThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ threadId, pinned }: { threadId: string; pinned: boolean }) => {
      const { data } = await api.patch<Thread>(`/threads/${threadId}`, { pinned });
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["threads"] });
    },
  });
}
