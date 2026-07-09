import { NextRequest, NextResponse } from "next/server";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

function backendApiBaseUrl(): string {
  return (
    process.env.MARGIN_API_BASE_URL ??
    process.env.NEXT_PUBLIC_MARGIN_API_BASE_URL ??
    DEFAULT_API_BASE_URL
  ).replace(/\/+$/, "");
}

async function proxyRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await context.params;
  const targetUrl = new URL(`${backendApiBaseUrl()}/api/${path.join("/")}`);
  targetUrl.search = request.nextUrl.search;
  const requestHeaders = new Headers(request.headers);
  requestHeaders.delete("host");

  const response = await fetch(targetUrl, {
    body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
    cache: "no-store",
    headers: requestHeaders,
    method: request.method,
  });
  const responseHeaders = new Headers(response.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");

  return new NextResponse(response.body, {
    headers: responseHeaders,
    status: response.status,
    statusText: response.statusText,
  });
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
