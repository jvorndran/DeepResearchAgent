import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { Pool } from "pg";

const databaseUrl = process.env.DATABASE_URL;
const authSecret =
  process.env.BETTER_AUTH_SECRET ??
  (process.env.NODE_ENV === "development" ? "dev-only-change-me-deep-research-agent" : undefined);

if (!authSecret) {
  throw new Error("BETTER_AUTH_SECRET is required outside development.");
}

export const auth = betterAuth({
  database: databaseUrl
    ? new Pool({
        connectionString: databaseUrl,
      })
    : undefined,
  secret: authSecret,
  baseURL: process.env.BETTER_AUTH_URL ?? "http://localhost:3000",
  trustedOrigins: [
    process.env.BETTER_AUTH_URL ?? "http://localhost:3000",
    process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000",
  ],
  emailAndPassword: {
    enabled: true,
  },
  plugins: [nextCookies()],
});
