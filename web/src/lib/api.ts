import { mockBoardApi } from "@/lib/mock/board";
import { mockTopicsApi } from "@/lib/mock/topics";
import type { Topic } from "@/types";

export interface MutationResultItem {
  id: string;
  ok: boolean;
  error?: string;
}

export interface MutationResponse {
  ok: boolean;
  results: MutationResultItem[];
  image_url?: string;
  scheduled_at?: string;
  rescheduled?: boolean;
  error?: string;
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error(`Network error calling ${path}`);
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // non-JSON error body
  }
  if (!response.ok) {
    const message =
      body &&
      typeof body === "object" &&
      "error" in (body as Record<string, unknown>)
        ? String((body as Record<string, unknown>).error)
        : `Request failed with status ${response.status}`;
    throw new Error(message);
  }
  return body as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/** Strip server/exception noise so users see an actual problem, not a stack trace. */
export function friendlyError(err: unknown): string {
  let message = err instanceof Error ? err.message : String(err);
  if (/APITimeoutError|timed out|TimeoutError/i.test(message)) {
    return "The AI request timed out. Give it another try.";
  }
  for (const prefix of [
    "BufferAPIError: ",
    "RuntimeError: ",
    "ValueError: ",
    "Error: ",
  ]) {
    if (message.startsWith(prefix)) {
      message = message.slice(prefix.length);
    }
  }
  if (/\(429\)|rate-limit/i.test(message)) {
    return "Buffer is rate-limiting requests right now. Wait a minute and try again.";
  }
  if (
    message.includes("Failed to fetch") ||
    message.includes("Network error")
  ) {
    return "Couldn't reach the server. Check your connection and try again.";
  }
  return message;
}

/** A post reference sent with mutation requests: id plus channel context. */
export interface PostRef {
  id: string;
  service: string;
  metadata?: Record<string, unknown> | null;
}

/**
 * True when the UI runs on in-memory mock data instead of the worker
 * (Buffer/D1/R2 assets). Set by `npm run web-mock`, which starts Vite with
 * `--mode mock` — constant for the whole session, so the mock layer is a
 * dead branch (and tree-shakeable) in normal dev and production builds.
 */
export const MOCK = import.meta.env.VITE_MOCK === "1";

const realBoardApi = {
  async updateText(posts: PostRef[], text: string): Promise<MutationResponse> {
    return request("/api/posts", jsonInit("PATCH", { posts, text }));
  },

  async acceptPosts(
    posts: PostRef[],
    dueAt: string | null,
    text?: string,
  ): Promise<MutationResponse> {
    return request(
      "/api/posts/accept",
      jsonInit("POST", { posts, due_at: dueAt, text }),
    );
  },

  async deletePosts(posts: PostRef[]): Promise<MutationResponse> {
    return request("/api/posts/delete", jsonInit("POST", { posts }));
  },

  async replaceImage(posts: PostRef[], file: File): Promise<MutationResponse> {
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () =>
        reject(new Error("Failed to read the selected image file"));
      reader.readAsDataURL(file);
    });
    return request(
      "/api/posts/image",
      jsonInit("POST", { posts, image: { data: dataUrl } }),
    );
  },
};

/** D1 topic management (independent of the Buffer-backed board). */
const realTopicsApi = {
  async listTopics(): Promise<{ topics: Topic[] }> {
    return request("/api/topics", { method: "GET" });
  },

  async addTopic(topic: string): Promise<{ ok: boolean }> {
    return request("/api/topics", jsonInit("POST", { topic }));
  },

  /** Clear used_at. An empty id list resets every used topic. */
  async resetTopics(ids: number[]): Promise<{ ok: boolean; reset: number }> {
    return request("/api/topics/reset", jsonInit("POST", { ids }));
  },

  async deleteTopic(id: number): Promise<{ ok: boolean }> {
    return request("/api/topics/delete", jsonInit("POST", { id }));
  },
};

export const boardApi = MOCK ? mockBoardApi : realBoardApi;
export const topicsApi = MOCK ? mockTopicsApi : realTopicsApi;
