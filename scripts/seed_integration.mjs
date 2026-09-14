// A dedicated local demo identity exercises the existing authenticated sync flow.
import fs from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../balanca-audit/apps/api/package.json', import.meta.url));
const bcrypt = require('bcryptjs');
const { Client } = require('pg');
const { assertDemoDatabaseTarget } = await import('../balanca-audit/apps/api/dist/demoSafety.js');
const settings = JSON.parse(fs.readFileSync(new URL('../.demo/runtime.json', import.meta.url), 'utf8'));
assertDemoDatabaseTarget(process.env.DATABASE_URL);
const client = new Client({connectionString:process.env.DATABASE_URL});
await client.connect();
try {
  const hash=await bcrypt.hash(settings.integration_password,12);
  await client.query(`INSERT INTO users(id,name,email,password_hash,role,active)
    VALUES ('oa-demo-integration','Integracao Ficticia','integracao@example.invalid',$1,'ANALYST',true)
    ON CONFLICT(id) DO UPDATE SET password_hash=EXCLUDED.password_hash`,[hash]);
} finally {await client.end();}
console.log('Identidade de integracao local configurada.');
