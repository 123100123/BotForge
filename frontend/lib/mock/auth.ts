import { ApiError } from "@/lib/errors";
import type { Me } from "@/lib/types";

/**
 * Mock of the backend auth endpoints (POST /auth/signup, POST /auth/login, POST /auth/logout, GET /me).
 * The "cookie" is a localStorage entry so a mock session survives a reload. Any email and password log in.
 */
const SESSION_KEY = "botforge.mock.user";
const MIN_PASSWORD = 10;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function read(): Me | null {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Me) : null;
  } catch {
    return null;
  }
}

function write(user: Me | null) {
  try {
    if (user) window.localStorage.setItem(SESSION_KEY, JSON.stringify(user));
    else window.localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable: the mock session just will not survive a reload */
  }
}

export function mockMe(): Me {
  const user = read();
  if (!user) throw new ApiError("auth_required", "نشست شما منقضی شده است؛ دوباره وارد شوید.", 401);
  return user;
}

export function mockLogin(email: string): Me {
  const user = { id: "mock-user", email };
  write(user);
  return user;
}

/** Mirrors the backend's signup validation: `invalid_email`, `weak_password`, and `email_taken` (taken@...). */
export function mockSignup(email: string, password: string): Me {
  if (!EMAIL_RE.test(email)) throw new ApiError("invalid_email", "invalid email", 422);
  if (password.length < MIN_PASSWORD) throw new ApiError("weak_password", "weak password", 422);
  if (email.toLowerCase().startsWith("taken@")) throw new ApiError("email_taken", "email taken", 409);
  return mockLogin(email);
}

export function mockLogout(): void {
  write(null);
}
