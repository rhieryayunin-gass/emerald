import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET() {
  const cookieStore = await cookies();
  if (!verifySession(cookieStore.get(SESSION_COOKIE)?.value)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const base = process.env.EMERALD_API_BASE_URL?.replace(/\/$/, "");
  const token = process.env.EMERALD_API_TOKEN;
  if (!base || !token) {
    return NextResponse.json({ error: "Konfigurasi backend belum lengkap" }, { status: 503 });
  }
  try {
    const response = await fetch(`${base}/calibration/report`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(4500),
    });
    if (!response.ok) {
      return NextResponse.json({ error: "Laporan belum tersedia atau perlu diperbarui" }, { status: response.status });
    }
    return new NextResponse(JSON.stringify(await response.json(), null, 2), {
      headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store",
        "Content-Disposition": "attachment; filename=emerald-calibration.json" },
    });
  } catch {
    return NextResponse.json({ error: "Backend tidak dapat dihubungi" }, { status: 502 });
  }
}
