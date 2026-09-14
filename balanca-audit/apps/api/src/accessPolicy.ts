import type { UserRole } from "@balanca/shared";

type PortalIdentity = {
  email: string;
  role: string;
};

export function portalIdentityToBalancaRole(
  portalUser: PortalIdentity,
  analystEmails: readonly string[]
): UserRole {
  if (portalUser.role.trim().toLowerCase() === "admin") {
    return "ADMIN";
  }

  const email = portalUser.email.trim().toLowerCase();
  return analystEmails.includes(email) ? "ANALYST" : "VIEWER";
}
