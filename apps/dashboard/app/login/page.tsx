import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import LoginForm from "./login-form";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const cookieStore = await cookies();
  if (verifySession(cookieStore.get(SESSION_COOKIE)?.value)) redirect("/");
  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="brand-mark" aria-hidden="true">E</div>
        <p className="eyebrow">RIRI EMERALD</p>
        <h1>Control Center</h1>
        <p className="login-copy">
          Dashboard privat untuk telemetry XAUUSD, kontrol risiko, dan evaluasi shadow model.
        </p>
        <LoginForm />
        <p className="login-footnote">Protected session · Demo trading environment</p>
      </section>
    </main>
  );
}
