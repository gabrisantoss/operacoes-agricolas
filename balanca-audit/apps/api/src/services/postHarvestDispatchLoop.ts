export async function dispatchClaimedItemsOneAtATime<TItem, TResult>(input: {
  limit: number;
  claimOne: () => TItem | null | Promise<TItem | null>;
  dispatchOne: (item: TItem) => TResult | Promise<TResult>;
}) {
  const results: TResult[] = [];
  const limit = normalizeDispatchLimit(input.limit);

  for (let index = 0; index < limit; index += 1) {
    const item = await input.claimOne();
    if (!item) break;
    results.push(await input.dispatchOne(item));
  }

  return results;
}

export function normalizeDispatchLimit(value: number) {
  const parsed = Number.isFinite(value) ? Math.trunc(value) : 50;
  return Math.min(Math.max(parsed, 1), 500);
}
