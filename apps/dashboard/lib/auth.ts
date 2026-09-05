import { createHmac, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE = "emerald_session";
const SESSION_SECONDS = 8 * 60 * 60;

function secret(): string {
  const value = process.env.EMERALD_SESSION_SECRET;
  if (!value || value.length < 32) {
    throw new Error("EMERALD_SESSION_SECRET must contain at least 32 characters");
  }
  return value;
}

function signature(expiry: string): string {
  return createHmac("sha256", secret()).update(`emerald-session:${expiry}`).digest("hex");
}

function constantTimeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left);
  const rightBuffer = Buffer.from(right);
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}

export function verifyPassword(candidate: string): boolean {
  const expected = process.env.EMERALD_DASHBOARD_PASSWORD;
  return Boolean(expected && expected.length >= 12 && constantTimeEqual(candidate, expected));
}

export function createSession(): { token: string; maxAge: number } {
  const expiry = String(Math.floor(Date.now() / 1000) + SESSION_SECONDS);
  return { token: `${expiry}.${signature(expiry)}`, maxAge: SESSION_SECONDS };
}

export function verifySession(token: string | undefined): boolean {
  if (!token) return false;
  const [expiry, suppliedSignature, extra] = token.split(".");
  if (!expiry || !suppliedSignature || extra) return false;
  const expiryNumber = Number(expiry);
  if (!Number.isInteger(expiryNumber) || expiryNumber <= Date.now() / 1000) return false;
  return constantTimeEqual(suppliedSignature, signature(expiry));
}
