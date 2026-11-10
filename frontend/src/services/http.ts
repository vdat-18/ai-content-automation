export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

/** What a person should read when a request fails; the raw detail is only for the details link. */
export function friendlyMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if ([0, 502, 503, 504].includes(error.status)) {
      return "The AI service is busy or not reachable right now. Nothing was lost, please try again in a minute.";
    }
    if (error.status === 409) return error.message;
    if (error.status === 413) return "That file is too large. Choose a smaller one and try again.";
    if (error.status >= 500) return "Something went wrong on our side. Please try again shortly.";
  }
  return "We could not finish that step. Please try again.";
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new ApiError(payload?.detail ?? `API returned ${response.status}`, response.status);
  }
  return response.json() as Promise<T>;
}

export function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, { signal });
}

export function postJson<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    signal,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
}

export function putJson<T>(path: string, body: object, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, {
    method: "PUT",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function putFile<T>(path: string, file: File, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, { method: "PUT", signal, headers: { "Content-Type": file.type }, body: file });
}

export function deleteJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, { method: "DELETE", signal });
}
