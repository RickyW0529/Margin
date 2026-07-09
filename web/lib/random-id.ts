/**
 * @fileoverview Browser-safe client ID helpers.
 */

export function createClientId(prefix: string): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID === "function") {
    return randomUUID.call(globalThis.crypto);
  }

  const randomBytes = createRandomHex();
  return `${prefix}-${Date.now().toString(36)}-${randomBytes}`;
}

function createRandomHex(): string {
  const getRandomValues = globalThis.crypto?.getRandomValues;
  if (typeof getRandomValues === "function") {
    const bytes = new Uint8Array(8);
    getRandomValues.call(globalThis.crypto, bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  return Math.random().toString(36).slice(2, 12);
}
