// Who a request acts as and which data it sees: scope 0 is the real data, a test session has its own.
import { AsyncLocalStorage } from 'node:async_hooks';

export const UNKNOWN = 'Unknown';
export const SERVICE_ACTORS = ['ingestion-worker', 'notification-service'];

export interface Context {
  scope: number;
  actor: string;
  session?: string;
}

const store = new AsyncLocalStorage<Context>();

export const runIn = <T>(ctx: Context, fn: () => T) => store.run(ctx, fn);
export const current = (): Context => store.getStore() ?? { scope: 0, actor: UNKNOWN };
