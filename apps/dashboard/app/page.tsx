import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import Dashboard from "./ui/dashboard";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const cookieStore = await cookies();
  if (!verifySession(cookieStore.get(SESSION_COOKIE)?.value)) {
    redirect("/login");
  }
  return <Dashboard />;
}
