/** This distribution is deliberately incapable of using a production database. */
export function assertDemoDatabaseTarget(value: string) {
  const target = new URL(value);
  if (!['postgres:', 'postgresql:'].includes(target.protocol) ||
      !['127.0.0.1', 'localhost'].includes(target.hostname) ||
      target.port !== '55439' || !target.pathname.startsWith('/oa_demo_')) {
    throw new Error('Demonstracao isolada: use somente oa_demo_* em 127.0.0.1:55439.');
  }
}
