import { headers } from "next/headers";
import { auth } from "@/lib/auth";
import { stripLegacyBetterAuthCookie } from "@/lib/auth-cookies";

export async function getServerSession() {
  try {
    return await auth.api.getSession({ headers: stripLegacyBetterAuthCookie(await headers()) });
  } catch (error) {
    if (
      error &&
      typeof error === "object" &&
      "digest" in error &&
      error.digest === "DYNAMIC_SERVER_USAGE"
    ) {
      throw error;
    }
    console.warn("Ignoring invalid auth session cookie", error);
    return null;
  }
}
