// Minimal same-origin API client for /api/v1 (Caddy serves SPA and API on one
// origin — no CORS). The typed OpenAPI-generated client replaces the hand-typed
// interfaces in WP-09; this stays the transport layer.

export interface ApiConfig {
  auth_mode: string;
  clerk_publishable_key?: string;
  otel_enabled?: boolean;
  otel_traces_url?: string;
}

/** The uniform backend error envelope, surfaced as a typed exception. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  token?: string | null;
  method?: string;
  body?: unknown;
}

/** Shared transport: builds the request, throws ApiError on a non-ok envelope,
 *  and returns the raw Response for the caller to read (or ignore). */
async function request(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  if (options.token) {
    headers["Authorization"] = `Bearer ${options.token}`;
  }
  // FormData (OPML upload) is sent as-is so the browser sets the multipart
  // boundary; only JSON bodies get an explicit Content-Type.
  const isForm = options.body instanceof FormData;
  if (options.body !== undefined && !isForm) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`/api/v1${path}`, {
    method: options.method ?? "GET",
    headers,
    body:
      options.body === undefined
        ? undefined
        : isForm
          ? (options.body as FormData)
          : JSON.stringify(options.body),
  });
  if (!response.ok) {
    let code = "internal";
    let message = response.statusText || `HTTP ${response.status}`;
    try {
      const data: unknown = await response.json();
      const error = (data as { error?: { code?: string; message?: string } }).error;
      if (error?.code) code = error.code;
      if (error?.message) message = error.message;
    } catch {
      // non-JSON error body; keep the fallback code/message
    }
    throw new ApiError(response.status, code, message);
  }
  return response;
}

/** Call a JSON endpoint and parse its body as T. */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await request(path, options);
  return (await response.json()) as T;
}

/** Call an endpoint whose success is 204 No Content (the DELETEs) — no body read,
 *  so there's no `undefined as T` cast. */
export async function apiFetchVoid(path: string, options: RequestOptions = {}): Promise<void> {
  await request(path, options);
}

export function getConfig(): Promise<ApiConfig> {
  return apiFetch<ApiConfig>("/config");
}
