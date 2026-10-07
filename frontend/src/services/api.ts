import { useAuth } from "../stores/auth";

const BASE: string = import.meta.env.VITE_API_BASE ?? "/api/v1";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string, public fields?: { field: string; message: string }[]) {
    super(message);
  }
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    const e = body.error ?? {};
    return new ApiError(res.status, e.code ?? "error", e.message ?? res.statusText, e.request_id, e.details?.fields);
  } catch {
    return new ApiError(res.status, "error", `Request failed (${res.status}).`);
  }
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const token = useAuth.getState().token;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the server. Check your connection and try again.");
  }
  if (res.status === 401 && token) useAuth.getState().signOut();
  if (!res.ok) throw await parseError(res);
  return res;
}

async function json<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await raw(path, { method, headers: body === undefined ? {} : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => json<T>(path, "GET"),
  post: <T>(path: string, body?: unknown) => json<T>(path, "POST", body ?? {}),
  put: <T>(path: string, body: unknown) => json<T>(path, "PUT", body),
  patch: <T>(path: string, body: unknown) => json<T>(path, "PATCH", body),
  del: (path: string) => json<void>(path, "DELETE"),
  async upload<T>(path: string, form: FormData): Promise<T> {
    const res = await raw(path, { method: "POST", body: form });
    return (await res.json()) as T;
  },
  async blobUrl(path: string): Promise<string> {
    const res = await raw(path);
    return URL.createObjectURL(await res.blob());
  },
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const f = e.fields?.length ? ` (${e.fields.map((x) => `${x.field}: ${x.message}`).join("; ")})` : "";
    return e.message + f + (e.requestId ? ` Reference: ${e.requestId}.` : "");
  }
  return e instanceof Error ? e.message : "Something went wrong.";
}
