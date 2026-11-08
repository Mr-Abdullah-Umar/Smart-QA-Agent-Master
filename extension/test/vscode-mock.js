/**
 * Minimal stand-in for the `vscode` module so compiled sources can be unit tested with node:test.
 * Install once with `require("./vscode-mock")` before requiring anything from ../out.
 */
const Module = require("module");

const settings = new Map();

class EventEmitter {
  constructor() {
    this.listeners = [];
    this.event = (fn) => {
      this.listeners.push(fn);
      return { dispose() {} };
    };
  }
  fire(value) {
    this.listeners.forEach((fn) => fn(value));
  }
}

const vscode = {
  EventEmitter,
  ConfigurationTarget: { Global: 1 },
  workspace: {
    getConfiguration(section) {
      return {
        get: (key, fallback) => {
          const full = `${section}.${key}`;
          return settings.has(full) ? settings.get(full) : fallback;
        },
        update: async (key, value) => {
          settings.set(`${section}.${key}`, value);
        },
      };
    },
  },
  lm: {
    onDidChangeChatModels: () => ({ dispose() {} }),
    selectChatModels: async () => [],
  },
  LanguageModelError: class extends Error {},
};

const originalLoad = Module._load;
Module._load = function load(request, ...rest) {
  if (request === "vscode") return vscode;
  return originalLoad.call(this, request, ...rest);
};

/** In-memory replacement for HarnessSecretManager. */
class MemorySecrets {
  constructor() {
    this.keys = new Map();
  }
  async getApiKey(provider) {
    return this.keys.get(provider);
  }
  async setApiKey(provider, key) {
    this.keys.set(provider, key);
  }
  async deleteApiKey(provider) {
    this.keys.delete(provider);
  }
}

module.exports = { vscode, settings, MemorySecrets };
