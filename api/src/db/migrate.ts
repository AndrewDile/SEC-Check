// Applies db/migrations/*.sql in name order, once each, recording them in schema_migrations.
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import mysql, { type RowDataPacket } from 'mysql2/promise';

const DIR = process.env.MIGRATIONS_DIR ?? fileURLToPath(new URL('../../../db/migrations', import.meta.url));

export async function migrate(dir = DIR) {
  const c = await mysql.createConnection({
    host: process.env.DB_HOST ?? 'localhost',
    port: Number(process.env.DB_PORT ?? 3306),
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,
    database: process.env.DB_NAME ?? 'seccheck',
    multipleStatements: true,
  });
  try {
    await c.query(
      'CREATE TABLE IF NOT EXISTS schema_migrations (name VARCHAR(255) PRIMARY KEY, applied_at DATETIME(3) NOT NULL)',
    );
    // Databases made before this runner existed already have 001 (from MySQL's init scripts)
    const [[{ fresh }]] = await c.query<RowDataPacket[]>('SELECT COUNT(*) = 0 AS fresh FROM schema_migrations');
    const [legacy] = await c.query<RowDataPacket[]>("SHOW TABLES LIKE 'incidents'");
    if (fresh && legacy.length)
      await c.query("INSERT INTO schema_migrations VALUES ('001_initial.sql', UTC_TIMESTAMP(3))");
    const [rows] = await c.query<RowDataPacket[]>('SELECT name FROM schema_migrations');
    const done = new Set(rows.map((r) => r.name));
    for (const name of (await readdir(dir)).filter((f) => f.endsWith('.sql')).sort()) {
      if (done.has(name)) continue;
      console.log(`applying migration ${name}`);
      await c.query(await readFile(join(dir, name), 'utf8'));
      await c.query('INSERT INTO schema_migrations VALUES (?, UTC_TIMESTAMP(3))', [name]);
    }
  } finally {
    await c.end();
  }
}
