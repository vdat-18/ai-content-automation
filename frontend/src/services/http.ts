export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export function marketingErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 502 || error.status === 503 || error.status === 504 || error.status === 0) {
      return "The creative service is taking longer than expected. Your input is still here — please try again in a moment.";
    }
    if (error.status === 409) {
      return "This request changed while it was being prepared. Review your input and try again.";
    }
    if (error.status === 413) {
      return "One or more files are too large. Choose smaller files and try again.";
    }
    if (error.status >= 500) {
      return "The creative service is temporarily unavailable. Your input is still here — please try again shortly.";
    }
  }
  return "We couldn't complete this step. Your input is still here — please try again.";
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

export async function deleteRequest(path: string, signal?: AbortSignal): Promise<void> {
  const response = await fetch(path, { method: "DELETE", signal });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new ApiError(payload?.detail ?? `API returned ${response.status}`, response.status);
  }
}
