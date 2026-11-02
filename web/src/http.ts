let csrfToken = "";
export function setCsrfToken(value: string) {
  csrfToken = value;
}
export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch("/api" + path, {
    credentials: "same-origin",
    ...(body !== undefined
      ? {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
          },
          body: JSON.stringify(body),
        }
      : {}),
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("The server returned an unexpected response");
  }
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login")
      window.dispatchEvent(new Event("agentscope-session-expired"));
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Invalid request",
    );
  }
  return data;
}
