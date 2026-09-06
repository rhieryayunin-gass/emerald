"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginForm() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!response.ok) {
        setError("Password tidak valid.");
        return;
      }
      router.replace("/");
      router.refresh();
    } catch {
      setError("Dashboard tidak dapat dihubungi.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="login-form" onSubmit={submit}>
      <label htmlFor="password">Dashboard password</label>
      <input
        id="password"
        name="password"
        type="password"
        autoComplete="current-password"
        minLength={12}
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        placeholder="Masukkan password"
      />
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button type="submit" disabled={loading}>
        {loading ? "Memverifikasi…" : "Masuk ke dashboard"}
      </button>
    </form>
  );
}
