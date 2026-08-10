export type Role = "user" | "assistant" | "system" | "tool";

export interface User {
  id: string;
  email: string;
  username: string;
  full_name?: string | null;
  avatar_url?: string | null;
  role: string;
  provider: string;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface Thread {
  id: string;
  title: string;
  status: string;
  pinned: boolean;
  metadata_: Record<string, unknown>;
  model?: string | null;
  last_message_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  thread_id: string;
  role: Role;
  content: string;
  attachments: Record<string, unknown>[];
  images: string[];
  tokens?: number | null;
  latency_ms?: number | null;
  cost?: number | null;
  model?: string | null;
  metadata_: Record<string, unknown>;
  created_at: string;
}

export interface ModelInfo {
  name: string;
  provider: string;
  display_name: string;
  description: string;
  is_available: boolean;
  capabilities: string[];
  context_window?: number | null;
}

export interface ModelList {
  default: string;
  fallback_chain: string[];
  models: ModelInfo[];
}

export interface ChatRequest {
  thread_id?: string | null;
  message: string;
  model?: string | null;
  provider?: string | null;
  stream: boolean;
  attachments?: { type: string; name: string; url?: string | null; size?: number | null }[];
  images?: string[];
  metadata_?: Record<string, unknown>;
}

export interface ChatResponse {
  thread_id: string;
  message_id: string;
  content: string;
  model: string;
  provider: string;
  tokens: number;
  latency_ms: number;
  cost: number;
  citations: Record<string, unknown>[];
  metadata_: Record<string, unknown>;
}

export interface StreamEvent {
  type: "start" | "token" | "message" | "done" | "error" | "tool_call" | "citation";
  content?: string | null;
  data?: Record<string, unknown> | null;
}

export interface Memory {
  id: string;
  memory_type: string;
  content: string;
  key?: string | null;
  importance: number;
  metadata_: Record<string, unknown>;
  created_at: string;
}

export interface FileUploadResult {
  file_id: string;
  filename: string;
  content_type: string;
  size: number;
  url: string;
  category: string;
}

export interface DocumentInfo {
  id: string;
  thread_id?: string | null;
  filename: string;
  file_type: string;
  file_size: number;
  status: string;
  chunk_count: number;
  metadata_?: Record<string, unknown>;
  created_at: string;
}

export interface AiTool {
  name: string;
  description: string;
  example_prompt: string;
}
