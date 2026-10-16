import i18n from "../i18n";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly params: Record<string, unknown>;
  readonly fields: { field: string; code: string }[];

  constructor(status: number, code: string, message: string, params: Record<string, unknown> = {}, fields: { field: string; code: string }[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.params = params;
    this.fields = fields;
  }
}

let csrfToken: string | null = null;
let csrfRequest: Promise<string> | null = null;

async function loadCsrf(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", { credentials: "same-origin" });
  const body = (await response.json()) as { csrf_token: string };
  csrfToken = body.csrf_token;
  return csrfToken;
}

export async function ensureCsrf(force = false): Promise<string> {
  if (force) {
    csrfToken = null;
  }
  if (csrfToken) {
    return csrfToken;
  }
  csrfRequest ??= loadCsrf().finally(() => {
    csrfRequest = null;
  });
  return csrfRequest;
}

export function resetCsrf(): void {
  csrfToken = null;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  form?: FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL("/api/v1" + path, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  }
  return url.pathname + url.search;
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const payload = (await response.json()) as {
      error?: { code: string; message: string; params?: Record<string, unknown>; fields?: { field: string; code: string }[] };
    };
    const error = payload.error;
    if (error) {
      return new ApiError(response.status, error.code, error.message, error.params ?? {}, error.fields ?? []);
    }
  } catch {
    return new ApiError(response.status, "request_failed", "request_failed");
  }
  return new ApiError(response.status, "request_failed", "request_failed");
}

async function send(path: string, options: RequestOptions, retried: boolean): Promise<Response> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", "Accept-Language": i18n.language || "hu" };
  let body: BodyInit | undefined;
  if (method !== "GET") {
    headers["X-CSRF-Token"] = await ensureCsrf();
  }
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const response = await fetch(buildUrl(path, options.query), { method, headers, body, credentials: "same-origin", signal: options.signal });
  if (response.status === 403 && !retried && method !== "GET") {
    const payload = (await response.clone().json().catch(() => null)) as { error?: { code?: string } } | null;
    if (payload?.error?.code === "csrf_failed") {
      await ensureCsrf(true);
      return send(path, options, true);
    }
  }
  return response;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options, false);
  if (!response.ok) {
    throw await toError(response);
  }
  return (await response.json()) as T;
}

interface UploadOptions {
  query?: RequestOptions["query"];
  signal?: AbortSignal;
  onProgress?: (percent: number) => void;
}

async function uploadProgress<T>(path: string, file: File, options: UploadOptions, retried = false): Promise<T> {
  const csrf = await ensureCsrf();
  if (options.signal?.aborted) {
    throw new DOMException("Aborted", "AbortError");
  }
  const response = await new Promise<Response>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abort = () => xhr.abort();
    const done = () => options.signal?.removeEventListener("abort", abort);
    xhr.open("POST", buildUrl(path, options.query));
    xhr.withCredentials = true;
    xhr.timeout = 30 * 60 * 1000;
    xhr.setRequestHeader("Accept", "application/json");
    xhr.setRequestHeader("Accept-Language", i18n.language || "hu");
    xhr.setRequestHeader("X-CSRF-Token", csrf);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        options.onProgress?.(Math.min(99, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onload = () => {
      done();
      if (!xhr.status) {
        reject(new TypeError("network_error"));
        return;
      }
      resolve(new Response(xhr.responseText, { status: xhr.status }));
    };
    xhr.onerror = xhr.ontimeout = () => {
      done();
      reject(new TypeError("network_error"));
    };
    xhr.onabort = () => {
      done();
      reject(new DOMException("Aborted", "AbortError"));
    };
    options.signal?.addEventListener("abort", abort, { once: true });
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
  if (!response.ok) {
    const error = await toError(response);
    if (error.code === "csrf_failed" && !retried) {
      await ensureCsrf(true);
      return uploadProgress<T>(path, file, options, true);
    }
    throw error;
  }
  options.onProgress?.(100);
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) => request<T>(path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body ?? {} }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body: body ?? {} }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body: body ?? {} }),
  del: <T>(path: string, body?: unknown, query?: RequestOptions["query"]) => request<T>(path, { method: "DELETE", body, query }),
  upload: <T>(path: string, file: File, options?: UploadOptions) => {
    if (options?.onProgress) {
      return uploadProgress<T>(path, file, options);
    }
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, { method: "POST", form, query: options?.query, signal: options?.signal });
  },
};

export function describeError(error: unknown): { code: string; params: Record<string, unknown> } {
  if (error instanceof ApiError) {
    return { code: error.code, params: error.params };
  }
  return { code: "network_error", params: {} };
}
