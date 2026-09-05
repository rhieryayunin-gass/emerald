import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE, verifySession } from "@/lib/auth";
import type {
  DashboardSnapshot,
  Health,
  Incident,
  ShadowEvent,
  ShadowMetrics,
  TelemetryReadiness,
} from "@/lib/types";

export const dynamic = "force-dynamic";

type FetchResult<T> = { data: T | null; error: string | null };

async function backendFetch<T>(path: string, authenticated = true): Promise<FetchResult<T>> {
  const baseUrl = process.env.EMERALD_API_BASE_URL?.replace(/\/$/, "");
  const apiToken = process.env.EMERALD_API_TOKEN;
  if (!baseUrl || (authenticated && !apiToken)) {
    return { data: null, error: `Server configuration missing for ${path}` };
  }
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      cache: "no-store",
      headers: authenticated ? { Authorization: `Bearer ${apiToken}` } : undefined,
      signal: AbortSignal.timeout(4500),
    });
    if (!response.ok) {
      return { data: null, error: `Backend ${path} returned HTTP ${response.status}` };
    }
    return { data: (await response.json()) as T, error: null };
  } catch {
    return { data: null, error: `Backend ${path} is unreachable` };
  }
}

export async function GET() {
  const cookieStore = await cookies();
  if (!verifySession(cookieStore.get(SESSION_COOKIE)?.value)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const [health, telemetry, metrics, incidentPayload, eventPayload] = await Promise.all([
    backendFetch<Health>("/health", false),
    backendFetch<TelemetryReadiness>("/telemetry/readiness"),
    backendFetch<ShadowMetrics>("/shadow/metrics"),
    backendFetch<{ incidents: Incident[] }>("/incidents"),
    backendFetch<{ events: ShadowEvent[] }>("/shadow/events?limit=50"),
  ]);
  const errors = [health, telemetry, metrics, incidentPayload, eventPayload]
    .map((result) => result.error)
    .filter((error): error is string => Boolean(error));
  const snapshot: DashboardSnapshot = {
    fetched_at: new Date().toISOString(),
    health: health.data,
    telemetry: telemetry.data,
    metrics: metrics.data,
    incidents: incidentPayload.data?.incidents ?? [],
    events: eventPayload.data?.events ?? [],
    errors,
  };
  return NextResponse.json(snapshot, {
    headers: { "Cache-Control": "private, no-store, max-age=0" },
  });
}
