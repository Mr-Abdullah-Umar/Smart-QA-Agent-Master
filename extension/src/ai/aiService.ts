/**
 * AI provider gateway used by the QA engine (engine -> extension `llm.chat` requests).
 *
 * - GitHub Copilot: VS Code Language Model API (no key; uses the signed-in Copilot account).
 * - API-key providers: OpenAI, Azure OpenAI, Anthropic, Google Gemini, or any
 *   OpenAI-compatible HTTPS endpoint. Keys live only in VS Code SecretStorage.
 *
 * Model lists are always fetched from the provider; nothing is hardcoded.
 */

import * as vscode from "vscode";
import { HarnessSecretManager } from "../security/secretStorage";

export type ProviderId =
  | "copilot"
  | "openai"
  | "azure-openai"
  | "anthropic"
  | "gemini"
  | "github-models"
  | "openai-compatible"
  | "none";

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ProviderInfo {
  id: ProviderId;
  label: string;
  needsKey: boolean;
  needsBaseUrl: boolean;
  defaultBaseUrl: string;
  keyHelp: string;
}

export const PROVIDERS: ProviderInfo[] = [
  {
    id: "copilot",
    label: "GitHub Copilot (VS Code)",
    needsKey: false,
    needsBaseUrl: false,
    defaultBaseUrl: "",
    keyHelp: "Uses your GitHub Copilot subscription through VS Code. No API key needed.",
  },
  {
    id: "openai",
    label: "OpenAI",
    needsKey: true,
    needsBaseUrl: false,
    defaultBaseUrl: "https://api.openai.com/v1",
    keyHelp: "Create a key at platform.openai.com > API keys.",
  },
  {
    id: "azure-openai",
    label: "Azure OpenAI",
    needsKey: true,
    needsBaseUrl: true,
    defaultBaseUrl: "",
    keyHelp: "Endpoint like https://<resource>.openai.azure.com; model = your deployment name.",
  },
  {
    id: "anthropic",
    label: "Anthropic Claude",
    needsKey: true,
    needsBaseUrl: false,
    defaultBaseUrl: "https://api.anthropic.com/v1",
    keyHelp: "Create a key at console.anthropic.com > API keys.",
  },
  {
    id: "gemini",
    label: "Google Gemini",
    needsKey: true,
    needsBaseUrl: false,
    defaultBaseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    keyHelp: "Create a key at aistudio.google.com > Get API key.",
  },
  {
    id: "github-models",
    label: "GitHub Models",
    needsKey: true,
    needsBaseUrl: false,
    defaultBaseUrl: "https://models.github.ai/inference",
    keyHelp: "GitHub > Settings > Developer settings > fine-grained token with 'Models: read'.",
  },
  {
    id: "openai-compatible",
    label: "OpenAI-compatible endpoint",
    needsKey: true,
    needsBaseUrl: true,
    defaultBaseUrl: "",
    keyHelp: "Any HTTPS endpoint implementing /chat/completions (e.g. OpenRouter, Groq, Together).",
  },
  {
    id: "none",
    label: "No AI (smoke suites only)",
    needsKey: false,
    needsBaseUrl: false,
    defaultBaseUrl: "",
    keyHelp: "Suites are drafted from the page structure without requirement analysis.",
  },
];

export interface AiSettings {
  provider: ProviderId;
  model: string;
  baseUrl: string;
  azureApiVersion: string;
}

export interface AiStatus {
  provider: ProviderId;
  providerLabel: string;
  model: string;
  ready: boolean;
  detail: string;
  hasKey: boolean;
}

const REQUEST_TIMEOUT_MS = 180_000;
const GITHUB_MODELS_CATALOG = "https://models.github.ai/catalog/models";

/** True when a provider rejected the request because the model does not accept `temperature`. */
export function rejectsTemperature(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return /HTTP 400/.test(message) && /temperature/i.test(message);
}

/** Normalizes the model lists of OpenAI-style, Anthropic, Gemini and GitHub Models catalogs. */
export function parseModelList(data: unknown): { id: string; name: string }[] {
  type Item = { id?: string; name?: string; display_name?: string };
  const record = (data || {}) as { data?: Item[]; models?: Item[] };
  const items: Item[] = Array.isArray(data) ? (data as Item[]) : record.data || record.models || [];
  const seen = new Set<string>();
  return items
    .map((m) => {
      const id = String(m.id || m.name || "").replace(/^models\//, "");
      return { id, name: m.display_name || (m.name && m.name !== m.id ? `${m.name} (${id})` : id) };
    })
    .filter((m) => m.id && !seen.has(m.id) && seen.add(m.id))
    .sort((a, b) => a.id.localeCompare(b.id));
}

export class AIService {
  private readonly changeEmitter = new vscode.EventEmitter<void>();
  public readonly onDidChange = this.changeEmitter.event;

  constructor(private readonly secrets: HarnessSecretManager) {
    vscode.lm.onDidChangeChatModels(() => this.changeEmitter.fire());
  }

  public settings(): AiSettings {
    const cfg = vscode.workspace.getConfiguration("qaHarness.ai");
    return {
      provider: cfg.get<ProviderId>("provider", "copilot"),
      model: cfg.get<string>("model", "").trim(),
      baseUrl: cfg.get<string>("baseUrl", "").trim().replace(/\/+$/, ""),
      azureApiVersion: cfg.get<string>("azureApiVersion", "2024-10-21").trim(),
    };
  }

  public async saveSettings(next: Partial<AiSettings>): Promise<void> {
    const cfg = vscode.workspace.getConfiguration("qaHarness.ai");
    const target = vscode.ConfigurationTarget.Global;
    if (next.provider !== undefined) await cfg.update("provider", next.provider, target);
    if (next.model !== undefined) await cfg.update("model", next.model, target);
    if (next.baseUrl !== undefined) await cfg.update("baseUrl", next.baseUrl, target);
    if (next.azureApiVersion !== undefined) {
      await cfg.update("azureApiVersion", next.azureApiVersion, target);
    }
    this.changeEmitter.fire();
  }

  public async setApiKey(provider: ProviderId, key: string): Promise<void> {
    await this.secrets.setApiKey(provider, key);
    this.changeEmitter.fire();
  }

  public async clearApiKey(provider: ProviderId): Promise<void> {
    await this.secrets.deleteApiKey(provider);
    this.changeEmitter.fire();
  }

  private info(id: ProviderId): ProviderInfo {
    return PROVIDERS.find((p) => p.id === id) || PROVIDERS[0];
  }

  private baseUrl(s: AiSettings): string {
    const url = s.baseUrl || this.info(s.provider).defaultBaseUrl;
    if (!url) {
      throw new Error(`Set the endpoint URL for ${this.info(s.provider).label}.`);
    }
    if (!/^https:\/\//i.test(url)) {
      throw new Error("AI endpoints must use https:// so the API key is never sent in clear text.");
    }
    return url;
  }

  public async status(): Promise<AiStatus> {
    const s = this.settings();
    const info = this.info(s.provider);
    const base = { provider: s.provider, providerLabel: info.label, model: s.model, hasKey: false };
    if (s.provider === "none") {
      return { ...base, ready: false, detail: "AI disabled: suites use page-structure smoke design." };
    }
    if (s.provider === "copilot") {
      const models = await this.copilotModels();
      if (!models.length) {
        return {
          ...base,
          ready: false,
          detail: "No Copilot chat models available. Install GitHub Copilot Chat and sign in.",
        };
      }
      const chosen = models.find((m) => m.id === s.model) || models[0];
      return { ...base, model: chosen.id, ready: true, detail: `Using ${chosen.name}` };
    }
    const hasKey = Boolean(await this.secrets.getApiKey(s.provider));
    if (!hasKey) {
      return { ...base, ready: false, detail: `Add your ${info.label} API key.` };
    }
    if (!s.model) {
      return { ...base, hasKey, ready: false, detail: "Choose a model." };
    }
    if (info.needsBaseUrl && !s.baseUrl) {
      return { ...base, hasKey, ready: false, detail: "Set the endpoint URL." };
    }
    return { ...base, hasKey, ready: true, detail: `Using ${s.model}` };
  }

  private async copilotModels(): Promise<vscode.LanguageModelChat[]> {
    try {
      return await vscode.lm.selectChatModels({ vendor: "copilot" });
    } catch {
      return [];
    }
  }

  public async listModels(): Promise<{ id: string; name: string }[]> {
    const s = this.settings();
    if (s.provider === "copilot") {
      return (await this.copilotModels()).map((m) => ({
        id: m.id,
        name: `${m.name} (${m.family})`,
      }));
    }
    if (s.provider === "none" || s.provider === "azure-openai") {
      return [];
    }
    const key = await this.requireKey(s.provider);
    const base = this.baseUrl(s);
    const headers: Record<string, string> =
      s.provider === "anthropic"
        ? { "x-api-key": key, "anthropic-version": "2023-06-01" }
        : { Authorization: `Bearer ${key}` };
    const url = s.provider === "github-models" && !s.baseUrl ? GITHUB_MODELS_CATALOG : `${base}/models`;
    return parseModelList(await this.fetchJson(url, { method: "GET", headers }));
  }

  private async requireKey(provider: ProviderId): Promise<string> {
    const key = await this.secrets.getApiKey(provider);
    if (!key) {
      throw new Error(`No API key stored for ${this.info(provider).label}. Open the AI Provider tab.`);
    }
    return key;
  }

  public async chat(
    messages: ChatMessage[],
    temperature = 0.2,
    token?: vscode.CancellationToken
  ): Promise<{ content: string; model: string }> {
    const s = this.settings();
    switch (s.provider) {
      case "copilot":
        return this.chatCopilot(messages, s, token);
      case "anthropic":
        return this.chatAnthropic(messages, temperature, s);
      case "azure-openai":
        return this.chatOpenAI(messages, temperature, s, true);
      case "openai":
      case "gemini":
      case "github-models":
      case "openai-compatible":
        return this.chatOpenAI(messages, temperature, s, false);
      default:
        throw new Error("No AI provider is connected. Open the AI Provider tab to connect one.");
    }
  }

  private async chatCopilot(
    messages: ChatMessage[],
    s: AiSettings,
    token?: vscode.CancellationToken
  ): Promise<{ content: string; model: string }> {
    const models = await this.copilotModels();
    if (!models.length) {
      throw new Error("GitHub Copilot is not available. Install Copilot Chat and sign in.");
    }
    const model = models.find((m) => m.id === s.model) || models[0];

    // The LM API has no system role: fold system prompts into the first user turn.
    const system = messages.filter((m) => m.role === "system").map((m) => m.content).join("\n\n");
    const turns = messages.filter((m) => m.role !== "system");
    const lmMessages = turns.map((m, i) => {
      const text = i === 0 && system ? `${system}\n\n${m.content}` : m.content;
      return m.role === "assistant"
        ? vscode.LanguageModelChatMessage.Assistant(text)
        : vscode.LanguageModelChatMessage.User(text);
    });
    if (!lmMessages.length && system) {
      lmMessages.push(vscode.LanguageModelChatMessage.User(system));
    }

    const cts = new vscode.CancellationTokenSource();
    const sub = token?.onCancellationRequested(() => cts.cancel());
    const timer = setTimeout(() => cts.cancel(), REQUEST_TIMEOUT_MS);
    try {
      const response = await model.sendRequest(
        lmMessages,
        { justification: "The QA Harness designs and analyzes test cases for your application." },
        cts.token
      );
      let content = "";
      for await (const part of response.text) {
        content += part;
      }
      return { content, model: `copilot/${model.id}` };
    } catch (e) {
      if (e instanceof vscode.LanguageModelError) {
        throw new Error(`Copilot request failed (${e.code}): ${e.message}`);
      }
      throw e;
    } finally {
      clearTimeout(timer);
      sub?.dispose();
      cts.dispose();
    }
  }

  private async chatOpenAI(
    messages: ChatMessage[],
    temperature: number,
    s: AiSettings,
    azure: boolean
  ): Promise<{ content: string; model: string }> {
    if (!s.model) {
      throw new Error("Choose a model in the AI Provider tab.");
    }
    const key = await this.requireKey(s.provider);
    const base = this.baseUrl(s);
    const url = azure
      ? `${base}/openai/deployments/${encodeURIComponent(s.model)}/chat/completions` +
        `?api-version=${encodeURIComponent(s.azureApiVersion)}`
      : `${base}/chat/completions`;
    const headers: Record<string, string> = azure
      ? { "api-key": key }
      : { Authorization: `Bearer ${key}` };
    const body: Record<string, unknown> = { messages, temperature };
    if (!azure) body.model = s.model;
    const post = () => this.fetchJson(url, { method: "POST", headers, body: JSON.stringify(body) });
    let data;
    try {
      data = await post();
    } catch (e) {
      if (!rejectsTemperature(e)) throw e;
      delete body.temperature;
      data = await post();
    }
    const content = data.choices?.[0]?.message?.content;
    if (typeof content !== "string") {
      throw new Error("The AI provider returned no message content.");
    }
    return { content, model: `${s.provider}/${s.model}` };
  }

  private async chatAnthropic(
    messages: ChatMessage[],
    temperature: number,
    s: AiSettings
  ): Promise<{ content: string; model: string }> {
    if (!s.model) {
      throw new Error("Choose a model in the AI Provider tab.");
    }
    const key = await this.requireKey("anthropic");
    const system = messages.filter((m) => m.role === "system").map((m) => m.content).join("\n\n");
    const body: Record<string, unknown> = {
      model: s.model,
      max_tokens: 8192,
      temperature,
      system: system || undefined,
      messages: messages
        .filter((m) => m.role !== "system")
        .map((m) => ({ role: m.role, content: m.content })),
    };
    const post = () =>
      this.fetchJson(`${this.baseUrl(s)}/messages`, {
        method: "POST",
        headers: { "x-api-key": key, "anthropic-version": "2023-06-01" },
        body: JSON.stringify(body),
      });
    let data;
    try {
      data = await post();
    } catch (e) {
      if (!rejectsTemperature(e)) throw e;
      delete body.temperature;
      data = await post();
    }
    const content = (data.content || [])
      .filter((p: { type?: string }) => p.type === "text")
      .map((p: { text?: string }) => p.text || "")
      .join("");
    return { content, model: `anthropic/${s.model}` };
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private async fetchJson(url: string, init: RequestInit): Promise<any> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        ...init,
        headers: { "Content-Type": "application/json", ...(init.headers || {}) },
        signal: controller.signal,
      });
      const text = await response.text();
      if (!response.ok) {
        throw new Error(`AI provider HTTP ${response.status}: ${text.slice(0, 300)}`);
      }
      return text ? JSON.parse(text) : {};
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") {
        throw new Error("AI provider request timed out.");
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  public async testConnection(): Promise<string> {
    const reply = await this.chat(
      [{ role: "user", content: "Reply with the single word OK." }],
      0
    );
    return `${reply.model} replied: ${reply.content.trim().slice(0, 60)}`;
  }
}
