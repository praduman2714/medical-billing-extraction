import { betterAuth } from "better-auth";
import { Pool } from "pg";

export const auth = betterAuth({
  database: new Pool({
    connectionString: process.env.DATABASE_URL || "postgresql://billing_app:billing_app@postgres:5432/billing",
    ssl: process.env.NODE_ENV === "production" ? { rejectUnauthorized: false } : undefined,
  }),
  emailAndPassword: {
    enabled: true,
  },
});
