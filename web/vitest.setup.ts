import "@testing-library/jest-dom/vitest";

function installStorage(): Storage {
  const memory = new Map<string, string>();
  return {
    get length() {
      return memory.size;
    },
    clear() {
      memory.clear();
    },
    getItem(key) {
      return memory.has(key) ? (memory.get(key) ?? null) : null;
    },
    key(index) {
      return Array.from(memory.keys())[index] ?? null;
    },
    removeItem(key) {
      memory.delete(key);
    },
    setItem(key, value) {
      memory.set(key, String(value));
    },
  } satisfies Storage;
}

if (typeof window !== "undefined") {
  let ls = window.localStorage;
  if (ls === undefined || typeof ls.getItem !== "function") {
    ls = installStorage();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: ls,
    });
  }
  let ss = window.sessionStorage;
  if (ss === undefined || typeof ss.getItem !== "function") {
    ss = installStorage();
    Object.defineProperty(window, "sessionStorage", {
      configurable: true,
      value: ss,
    });
  }
}