import { redirect } from "next/navigation";
import { UnauthenticatedError, getMe, type SessionUser } from "@/lib/api";

export type { SessionUser } from "@/lib/api";

/**
 * Resolve the signed-in user for a server component, or send them to login.
 *
 * Every page calls this first, so an expired or missing session lands on the
 * login screen instead of surfacing an API 401 as a runtime error.
 *
 * A user who still owes a password change is routed to that screen and cannot
 * navigate past it — the API refuses everything else for them anyway, so
 * without this redirect they would see a wall of 403s instead of the one form
 * that fixes it.
 */
export async function requireSession(
  opts: { allowPasswordChange?: boolean } = {},
): Promise<SessionUser> {
  let user: SessionUser;
  try {
    user = await getMe();
  } catch (e) {
    if (e instanceof UnauthenticatedError) redirect("/login");
    throw e;
  }
  if (user.must_change_password && !opts.allowPasswordChange) {
    redirect("/change-password");
  }
  return user;
}

/**
 * Like requireSession, but also demands a specific permission.
 *
 * Sending an unauthorised user to the first page they *can* open beats showing
 * them a dead end — the nav already hides what they cannot reach, so arriving
 * here usually means a stale link or a bookmark.
 */
export async function requirePermission(permission: string): Promise<SessionUser> {
  const user = await requireSession();
  if (!user.permissions.includes(permission)) {
    redirect(landingFor(user));
  }
  return user;
}

/** First page this user is actually allowed to see. */
export function landingFor(user: SessionUser): string {
  if (user.permissions.includes("mapping.view")) return "/";
  if (user.permissions.includes("mapped.view")) return "/mapped";
  if (user.permissions.includes("comparison.view")) return "/comparison";
  if (user.permissions.includes("review.decide")) return "/review";
  if (user.role === "admin") return "/admin";
  return "/no-access";
}

export function can(user: SessionUser | null, permission: string): boolean {
  return !!user?.permissions.includes(permission);
}
