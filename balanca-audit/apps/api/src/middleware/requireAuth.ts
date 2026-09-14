import type { NextFunction, Request, Response } from "express";
import jwt from "jsonwebtoken";
import { systemIdentity, type UserRole } from "@balanca/shared";
import { portalIdentityToBalancaRole } from "../accessPolicy.js";
import { createUser, findUserByEmail } from "../db.js";
import { env } from "../env.js";
import { localAccessIsAllowed } from "../runtimeSecurity.js";

type TokenPayload = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
};

type PortalSessionUser = {
  id: string;
  name: string;
  email: string;
  role: string;
};

const localUser = {
  id: "local-admin",
  name: "Operacoes Agricolas",
  email: "visitante@example.invalid",
  role: "ADMIN" as UserRole
};

function ensureLocalUser() {
  const current = findUserByEmail(localUser.email);

  if (current?.id === localUser.id && current.active) {
    return;
  }

  createUser({
    id: localUser.id,
    name: localUser.name,
    email: localUser.email,
    passwordHash: "local-access-disabled",
    role: localUser.role,
    active: true,
    replace: Boolean(current)
  });
}

function parseCookies(cookieHeader: string | undefined) {
  const cookies = new Map<string, string>();
  for (const item of (cookieHeader ?? "").split(";")) {
    const separator = item.indexOf("=");
    if (separator <= 0) {
      continue;
    }
    cookies.set(item.slice(0, separator).trim(), item.slice(separator + 1).trim());
  }
  return cookies;
}

async function readPortalUser(cookieHeader: string | undefined): Promise<PortalSessionUser | null> {
  const token = parseCookies(cookieHeader).get(env.portalSessionCookie);
  if (!token) {
    return null;
  }

  const cached = getCachedPortalSession(token);
  if (cached !== undefined) {
    return cached;
  }

  try {
    const sessionUrl = new URL("/api/session", env.portalSessionUrl);
    const response = await fetch(sessionUrl, {
      headers: {
        Accept: "application/json",
        Cookie: cookieHeader ?? ""
      },
      signal: AbortSignal.timeout(2_000)
    });
    if (!response.ok) {
      cachePortalSession(token, null, 2_000);
      return null;
    }
    const payload = (await response.json()) as { authenticated?: boolean; user?: PortalSessionUser };
    const user = payload.authenticated && payload.user ? payload.user : null;
    cachePortalSession(token, user);
    return user;
  } catch {
    cachePortalSession(token, null, 2_000);
    return null;
  }
}

function portalRoleToBalancaRole(portalUser: PortalSessionUser): UserRole {
  return portalIdentityToBalancaRole(portalUser, env.portalAnalystEmails);
}

function ensurePortalUser(portalUser: PortalSessionUser) {
  const current = findUserByEmail(portalUser.email);
  const id = current?.id ?? `portal-${portalUser.id}`;
  const role = portalRoleToBalancaRole(portalUser);
  const name = portalUser.name || portalUser.email;

  if (current?.active && current.name === name && current.role === role) {
    return {
      id: current.id,
      name: current.name,
      email: current.email,
      role: current.role
    };
  }

  createUser({
    id,
    name,
    email: portalUser.email,
    passwordHash: "portal-session",
    role,
    active: true,
    replace: true
  });

  return {
    id,
    name: portalUser.name || portalUser.email,
    email: portalUser.email,
    role
  };
}

type PortalSessionCacheEntry = {
  user: PortalSessionUser | null;
  expiresAt: number;
};

const portalSessionCache = new Map<string, PortalSessionCacheEntry>();
const portalSessionCacheMs = 45_000;  // era 10_000ms — aumentado para reduzir chamadas ao portal
const maxPortalSessionCacheItems = 2_000;  // era 500 — aumentado para atender mais usuários simultâneos

function getCachedPortalSession(token: string) {
  const cached = portalSessionCache.get(token);
  const now = Date.now();

  if (!cached) {
    return undefined;
  }

  if (cached.expiresAt <= now) {
    portalSessionCache.delete(token);
    return undefined;
  }

  return cached.user;
}

function cachePortalSession(token: string, user: PortalSessionUser | null, ttlMs = portalSessionCacheMs) {
  if (portalSessionCache.size >= maxPortalSessionCacheItems) {
    const firstKey = portalSessionCache.keys().next().value;
    if (firstKey) {
      portalSessionCache.delete(firstKey);
    }
  }

  portalSessionCache.set(token, {
    user,
    expiresAt: Date.now() + ttlMs
  });
}

export async function requireAuth(req: Request, res: Response, next: NextFunction) {
  const portalUser = await readPortalUser(req.headers.cookie);
  if (portalUser) {
    req.user = ensurePortalUser(portalUser);
    return next();
  }

  const header = req.headers.authorization;

  if (
    header === "Bearer local-access" &&
    localAccessIsAllowed({
      configured: env.allowLocalAccess,
      apiHost: env.host,
      remoteAddress: req.socket.remoteAddress
    })
  ) {
    ensureLocalUser();
    req.user = localUser;
    return next();
  }

  if (!header || header === "Bearer local-access") {
    return res.status(401).json({ message: `Login necessario pelo ${systemIdentity.currentName}.` });
  }

  if (!header.startsWith("Bearer ")) {
    return res.status(401).json({ message: "Sessao invalida ou expirada." });
  }

  try {
    const token = header.slice("Bearer ".length);
    const payload = jwt.verify(token, env.jwtSecret) as TokenPayload;
    const user = findUserByEmail(payload.email);

    if (!user?.active) {
      return res.status(401).json({ message: "Sessao invalida ou expirada." });
    }

    req.user = {
      id: user.id,
      name: user.name,
      email: user.email,
      role: user.role
    };
    return next();
  } catch {
    return res.status(401).json({ message: "Sessao invalida ou expirada." });
  }
}

export function requireRoles(allowedRoles: UserRole[]) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!req.user) {
      return res.status(401).json({ message: "Login necessario." });
    }

    if (!allowedRoles.includes(req.user.role)) {
      return res.status(403).json({ message: "Seu usuario possui acesso somente leitura." });
    }

    return next();
  };
}
