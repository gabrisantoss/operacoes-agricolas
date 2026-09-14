import bcrypt from "bcryptjs";
import { Router, type Request } from "express";
import jwt from "jsonwebtoken";
import { loginSchema } from "@balanca/shared";
import { findUserByEmail } from "../db.js";
import { env } from "../env.js";
import { requireAuth } from "../middleware/requireAuth.js";

export const authRouter = Router();

authRouter.post("/login", async (req, res) => {
  const input = loginSchema.safeParse(req.body);
  const loginValue = input.success ? input.data.email : String(req.body?.email ?? "");
  const rateLimit = loginRateLimitStatus(req, loginValue);

  if (!rateLimit.allowed) {
    res.setHeader("Retry-After", String(rateLimit.retryAfterSeconds));
    return res.status(429).json({ message: "Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente." });
  }

  if (!input.success) {
    registerFailedLogin(req, loginValue);
    return res.status(400).json({ message: "Dados de acesso invalidos." });
  }

  const user = findUserForLogin(input.data.email);

  if (!user?.active) {
    registerFailedLogin(req, input.data.email);
    return res.status(401).json({ message: "Usuario ou senha invalidos." });
  }

  const passwordMatches = await bcrypt.compare(input.data.password, user.passwordHash).catch(() => false);

  if (!passwordMatches) {
    registerFailedLogin(req, input.data.email);
    return res.status(401).json({ message: "Usuario ou senha invalidos." });
  }

  const publicUser = {
    id: user.id,
    name: user.name,
    email: user.email,
    role: user.role
  };

  const token = jwt.sign(publicUser, env.jwtSecret, { expiresIn: "12h" });
  clearFailedLogins(req, input.data.email);

  return res.json({ token, user: publicUser });
});

authRouter.get("/me", requireAuth, (req, res) => {
  return res.json({ user: req.user });
});

function findUserForLogin(value: string) {
  const login = value.trim().toLowerCase();
  const username = normalizeUsername(login);
  const email = login.includes("@") ? login : `${username}@example.invalid`;
  const user = findUserByEmail(email);

  if (user || login.includes("@")) {
    return user;
  }

  const firstName = username.split(".")[0];
  return firstName && firstName !== username ? findUserByEmail(`${firstName}@example.invalid`) : null;
}

function normalizeUsername(value: string) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\s+/g, ".")
    .replace(/[^a-z0-9.]/g, "");
}

type LoginBucket = {
  count: number;
  firstAttemptAt: number;
  blockedUntil: number;
};

const loginBuckets = new Map<string, LoginBucket>();
const loginWindowMs = 15 * 60 * 1000;
const accountMaxAttempts = 6;
const ipMaxAttempts = 20;

function loginRateLimitStatus(req: Request, loginValue: string) {
  cleanupLoginBuckets();
  const now = Date.now();
  const blockedBuckets = loginKeys(req, loginValue)
    .map((key) => loginBuckets.get(key))
    .filter((bucket): bucket is LoginBucket => Boolean(bucket?.blockedUntil && bucket.blockedUntil > now));

  if (blockedBuckets.length === 0) {
    return { allowed: true, retryAfterSeconds: 0 };
  }

  const retryAfterSeconds = Math.ceil(Math.max(...blockedBuckets.map((bucket) => bucket.blockedUntil - now)) / 1000);
  return { allowed: false, retryAfterSeconds };
}

function registerFailedLogin(req: Request, loginValue: string) {
  const now = Date.now();
  for (const { key, maxAttempts } of loginLimitTargets(req, loginValue)) {
    const current = loginBuckets.get(key);
    const bucket =
      current && now - current.firstAttemptAt <= loginWindowMs
        ? current
        : { count: 0, firstAttemptAt: now, blockedUntil: 0 };

    bucket.count += 1;
    if (bucket.count >= maxAttempts) {
      bucket.blockedUntil = now + loginWindowMs;
    }
    loginBuckets.set(key, bucket);
  }
}

function clearFailedLogins(req: Request, loginValue: string) {
  for (const key of loginKeys(req, loginValue)) {
    loginBuckets.delete(key);
  }
}

function cleanupLoginBuckets() {
  const now = Date.now();
  for (const [key, bucket] of loginBuckets) {
    if (now - bucket.firstAttemptAt > loginWindowMs && bucket.blockedUntil <= now) {
      loginBuckets.delete(key);
    }
  }
}

function loginLimitTargets(req: Request, loginValue: string) {
  const ip = clientIp(req);
  const login = normalizeLoginKey(loginValue);
  return [
    { key: `ip:${ip}`, maxAttempts: ipMaxAttempts },
    { key: `account:${login}`, maxAttempts: accountMaxAttempts }
  ];
}

function loginKeys(req: Request, loginValue: string) {
  return loginLimitTargets(req, loginValue).map((item) => item.key);
}

function clientIp(req: Request) {
  return (req.ip || req.socket.remoteAddress || "unknown").trim();
}

function normalizeLoginKey(value: string) {
  return value.trim().toLowerCase().slice(0, 180) || "empty";
}
