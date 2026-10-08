const FINGERPRINT = /a=fingerprint:(\S+)\s+([0-9A-Fa-f:]+)/g;

export function extractFingerprints(sdp: string | null | undefined): string[] {
  if (!sdp) {
    return [];
  }
  return Array.from(sdp.matchAll(FINGERPRINT), (match) => `${match[1].toLowerCase()} ${match[2].toUpperCase()}`);
}

export async function securityCode(localSdp: string | null | undefined, remoteSdp: string | null | undefined): Promise<string | null> {
  const local = extractFingerprints(localSdp)[0];
  const remote = extractFingerprints(remoteSdp)[0];
  if (!local || !remote) {
    return null;
  }
  const material = [local, remote].sort().join("|");
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(material)));
  let value = 0n;
  for (const byte of digest.slice(0, 5)) {
    value = (value << 8n) | BigInt(byte);
  }
  const digits = (value % 1_000_000_000_000n).toString().padStart(12, "0");
  return `${digits.slice(0, 4)} ${digits.slice(4, 8)} ${digits.slice(8, 12)}`;
}
