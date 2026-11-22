// Team contacts: where the notification service sends a team's notices. A webhook URL works like a password
// (anyone holding it can post), so it's only ever returned or audited masked.
import { DbError } from './db/api.js';

export const CHANNELS = ['email', 'slack', 'ms_teams'] as const;
export type ContactChannel = (typeof CHANNELS)[number];

// Exact host for Slack; Workflows webhook hosts for Teams. Parsed with URL, never matched by prefix, so the
// notifier can't be pointed at an internal address (http://api:3001) or a look-alike host.
const WEBHOOK_HOSTS: Record<'slack' | 'ms_teams', (host: string) => boolean> = {
  slack: (host) => host === 'hooks.slack.com',
  ms_teams: (host) => host.endsWith('.logic.azure.com') || host.endsWith('.api.powerplatform.com'),
};

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function invalid(message: string): never {
  throw new DbError('INVALID_DATA', message);
}

export function checkChannel(value: unknown): ContactChannel {
  if (!CHANNELS.includes(value as ContactChannel)) invalid(`Contact_Channel must be one of ${CHANNELS.join(', ')}.`);
  return value as ContactChannel;
}

export function checkContact(channel: ContactChannel, address: unknown): string {
  if (typeof address !== 'string' || !address) invalid('Contact must be a non-empty string.');
  if (channel === 'email') {
    if (address.length > 255 || !EMAIL.test(address)) invalid('Contact must be an email address.');
    return address;
  }
  if (address.length > 1024) invalid('Contact must be at most 1024 characters.');
  let url: URL;
  try {
    url = new URL(address);
  } catch {
    invalid('Contact must be a webhook URL.');
  }
  if (url.protocol !== 'https:' || url.username || url.password || !WEBHOOK_HOSTS[channel](url.hostname))
    invalid(`Contact isn't a ${channel === 'slack' ? 'Slack' : 'Teams Workflows'} webhook URL.`);
  return address;
}

// https://hooks.slack.com/…WXYZ: enough to tell two webhooks apart, not enough to use one
export function maskAddress(channel: string, address: string): string {
  if (channel === 'email') return address;
  try {
    return `https://${new URL(address).hostname}/…${address.slice(-4)}`;
  } catch {
    return '…';
  }
}
