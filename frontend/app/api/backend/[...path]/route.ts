import { type NextRequest } from "next/server";

const BACKEND_BASE_URL =
  process.env.BACKEND_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function backendUrl(path: string[], search: string): string {
  const joinedPath = path.map(encodeURIComponent).join("/");
  return `${BACKEND_BASE_URL.replace(/\/$/, "")}/${joinedPath}${search}`;
}

async function proxyBackendRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");

  const body = request.method === "GET" || request.method === "HEAD" ? undefined : request.body;
  const response = await fetch(backendUrl(path, request.nextUrl.search), {
    method: request.method,
    headers,
    body,
    duplex: "half",
    redirect: "manual",
  } as RequestInit & { duplex: "half" });

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

export const GET = proxyBackendRequest;
export const POST = proxyBackendRequest;
