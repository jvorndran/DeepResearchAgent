import { Pool } from "pg";
import { getMigrations } from "better-auth/db/migration";

const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) {
  console.error("DATABASE_URL is required to migrate Better Auth tables.");
  process.exit(1);
}

const pool = new Pool({ connectionString: databaseUrl });

try {
  const migrations = await getMigrations({
    database: pool,
    secret: process.env.BETTER_AUTH_SECRET ?? "dev-only-change-me-deep-research-agent",
    baseURL: process.env.BETTER_AUTH_URL ?? "http://localhost:3000",
    emailAndPassword: {
      enabled: true,
    },
  });

  await migrations.runMigrations();
  const created = migrations.toBeCreated.map((table) => table.table).join(", ") || "none";
  const added = migrations.toBeAdded.map((table) => table.table).join(", ") || "none";
  console.log(`Better Auth migrations complete. Created: ${created}. Added: ${added}.`);
} finally {
  await pool.end();
}
