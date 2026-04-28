export const LEGACY_BETTER_AUTH_SESSION_COOKIE = "better-auth.session";

export function stripLegacyBetterAuthCookie(source: Headers): Headers {
  const headers = new Headers(source);
  const cookie = headers.get("cookie");
  if (!cookie) return headers;

  const filtered = cookie
    .split(";")
    .map((part) => part.trim())
    .filter(
      (part) => part && !part.startsWith(`${LEGACY_BETTER_AUTH_SESSION_COOKIE}=`),
    )
    .join("; ");

  if (filtered) {
    headers.set("cookie", filtered);
  } else {
    headers.delete("cookie");
  }
  return headers;
}

export function expireLegacyBetterAuthCookie(headers: Headers): void {
  headers.append(
    "set-cookie",
    `${LEGACY_BETTER_AUTH_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax`,
  );
}
