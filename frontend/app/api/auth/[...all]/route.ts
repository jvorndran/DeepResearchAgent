import { auth } from "@/lib/auth";
import {
  expireLegacyBetterAuthCookie,
  stripLegacyBetterAuthCookie,
} from "@/lib/auth-cookies";

async function handleAuth(request: Request): Promise<Response> {
  const sanitizedRequest = new Request(request, {
    headers: stripLegacyBetterAuthCookie(request.headers),
  });
  const response = await auth.handler(sanitizedRequest);
  const headers = new Headers(response.headers);
  expireLegacyBetterAuthCookie(headers);

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export const GET = handleAuth;
export const POST = handleAuth;
