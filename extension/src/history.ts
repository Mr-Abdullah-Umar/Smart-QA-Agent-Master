import * as fs from "fs";
import * as path from "path";

/**
 * Run history: every suite design, update, retest, and regression is one session whose panel
 * events (messages, agent steps, cards, logs) are kept in .qa-harness/history/<id>.json so it
 * can be replayed read-only later. Only what the panel already showed is stored: secret values
 * never reach the panel, so they never reach history either.
 */

export type SessionKind = "suite" | "update" | "retest" | "retest-failed" | "regression";
export type SessionStatus = "running" | "waiting" | "passed" | "failed" | "error" | "cancelled";

export interface SessionSummary {
  id: string;
  kind: SessionKind;
  title: string;
  subtitle: string;
  startedAt: string;
  endedAt?: string;
  status: SessionStatus;
  stage?: string;
  steps: number;
  result?: { total: number; passed: number; failed: number };
}

export interface Session extends SessionSummary {
  events: Array<Record<string, unknown>>;
}

const RECORDED = new Set(["stage.update", "message.stream", "card.show", "activity", "notice", "user"]);
const WAITING_CARDS = new Set(["scope_card", "clarification_card", "review_card", "dry_run_card"]);
const MAX_EVENTS = 4000;
const MAX_LOG_CHARS = 400_000;
const ID_PATTERN = /^[A-Za-z0-9_-]{1,80}$/;

export class RunHistory {
  private current?: Session;
  private logChars = 0;
  private saveTimer?: NodeJS.Timeout;
  private listeners: Array<() => void> = [];

  constructor(private readonly root: () => string | undefined) {}

  public onDidChange(listener: () => void): void {
    this.listeners.push(listener);
  }

  public activeId(): string | undefined {
    return this.current?.id;
  }

  public start(kind: SessionKind, title: string, subtitle: string): Session {
    if (this.current && isLive(this.current.status)) {
      this.finish(this.current, "cancelled");
    }
    const now = new Date();
    this.current = {
      id: `${now.toISOString().replace(/[-:.TZ]/g, "").slice(0, 17)}-${Math.random()
        .toString(36)
        .slice(2, 8)}`,
      kind,
      title: title.slice(0, 120),
      subtitle: subtitle.slice(0, 200),
      startedAt: now.toISOString(),
      status: "running",
      steps: 0,
      events: [],
    };
    this.logChars = 0;
    this.persist(true);
    this.changed();
    return this.current;
  }

  /** Record one panel message into the active session. Returns true when it was recorded. */
  public record(message: Record<string, unknown>): boolean {
    const session = this.current;
    if (!session || !isLive(session.status) || !RECORDED.has(String(message.type))) return false;
    const event = { ...message, at: Date.now() };
    if (!this.merge(session, event)) {
      if (session.events.length >= MAX_EVENTS) return false;
      session.events.push(event);
    }
    const before = signature(session);
    this.apply(session, event);
    this.persist(!isLive(session.status));
    if (signature(session) !== before) this.changed();
    return true;
  }

  public list(): SessionSummary[] {
    const index = this.readIndex();
    if (this.current) {
      const at = index.findIndex((s) => s.id === this.current!.id);
      const summary = summarize(this.current);
      if (at >= 0) index[at] = summary;
      else index.unshift(summary);
    }
    return index.sort((a, b) => b.startedAt.localeCompare(a.startedAt));
  }

  public open(id: string): Session | undefined {
    if (this.current?.id === id) return this.current;
    const file = this.file(id);
    if (!file || !fs.existsSync(file)) return undefined;
    try {
      return JSON.parse(fs.readFileSync(file, "utf8")) as Session;
    } catch {
      return undefined;
    }
  }

  public delete(id: string): boolean {
    const file = this.file(id);
    if (!file) return false;
    if (this.current?.id === id) {
      if (isLive(this.current.status)) return false;
      this.current = undefined;
    }
    try {
      fs.rmSync(file, { force: true });
    } catch {
      return false;
    }
    this.writeIndex(this.readIndex().filter((s) => s.id !== id));
    this.changed();
    return true;
  }

  /** End the active session (e.g. the engine rejected the start request). */
  public end(status: SessionStatus): void {
    if (this.current) this.finish(this.current, status);
  }

  /** Flush pending writes (called on dispose). */
  public flush(): void {
    if (this.saveTimer) {
      clearTimeout(this.saveTimer);
      this.saveTimer = undefined;
      this.save();
    }
  }

  // ------------------------------------------------------------------ internals

  /** Coalesce streaming chunks and step progress so history stays compact. */
  private merge(session: Session, event: Record<string, unknown>): boolean {
    const last = session.events[session.events.length - 1];
    if (!last) return false;
    if (event.type === "message.stream" && last.type === "message.stream" && !last.complete) {
      if ((last.style || "") !== (event.style || "")) return false;
      const chunk = String(event.chunk || "");
      if (event.style === "log") {
        if (this.logChars >= MAX_LOG_CHARS) {
          last.complete = event.complete;
          return true;
        }
        this.logChars += chunk.length;
      }
      last.chunk = String(last.chunk || "") + chunk;
      last.complete = event.complete;
      return true;
    }
    if (
      event.type === "activity" &&
      event.phase === "update" &&
      last.type === "activity" &&
      last.phase === "update" &&
      last.id === event.id
    ) {
      last.detail = event.detail;
      return true;
    }
    if (event.type === "message.stream" && event.style === "log") {
      this.logChars += String(event.chunk || "").length;
    }
    return false;
  }

  private apply(session: Session, event: Record<string, unknown>): void {
    if (event.type === "activity" && event.phase === "start") {
      session.steps += 1;
      if (session.status === "waiting" && event.kind !== "wait") session.status = "running";
    }
    if (event.type === "card.show") {
      const card = String(event.card_type);
      const data = (event.data || {}) as Record<string, unknown>;
      if (WAITING_CARDS.has(card)) session.status = "waiting";
      if (card === "scope_card" && data.updates_existing_suite && session.kind === "suite") {
        session.kind = "update";
      }
      if (card === "report_card" || card === "regression_card") {
        const totals = (card === "regression_card" ? data.totals || {} : data) as Record<string, unknown>;
        const failed = Number(totals.failed || 0) + Number(totals.blocked || 0);
        const errors =
          card === "regression_card" &&
          ((data.suites as Array<Record<string, unknown>>) || []).some((s) => s.status === "error");
        session.result = { total: Number(totals.total || 0), passed: Number(totals.passed || 0), failed };
        if (card === "regression_card" || session.kind !== "regression") {
          this.finish(session, failed || errors ? "failed" : "passed");
        }
      }
    }
    if (event.type === "stage.update") {
      const stage = String(event.stage || "");
      session.stage = stage;
      if (stage === "CANCELLED") this.finish(session, "cancelled");
      else if (stage === "ERROR" && session.kind !== "regression") this.finish(session, "error");
      else if (stage !== "COMPLETED" && session.status === "waiting" && stage !== "STAGE_5_REVIEW_LOOP") {
        session.status = "running";
      }
    }
  }

  private finish(session: Session, status: SessionStatus): void {
    if (!isLive(session.status)) return;
    session.status = status;
    session.endedAt = new Date().toISOString();
    if (session === this.current) this.persist(true);
    else this.writeSession(session);
    this.changed();
  }

  private persist(immediate: boolean): void {
    if (immediate) {
      if (this.saveTimer) clearTimeout(this.saveTimer);
      this.saveTimer = undefined;
      this.save();
      return;
    }
    if (!this.saveTimer) {
      this.saveTimer = setTimeout(() => {
        this.saveTimer = undefined;
        this.save();
      }, 800);
    }
  }

  private save(): void {
    if (!this.current) return;
    this.writeSession(this.current);
  }

  private writeSession(session: Session): void {
    const dir = this.dir();
    if (!dir) return;
    try {
      fs.mkdirSync(dir, { recursive: true });
      writeAtomic(path.join(dir, `${session.id}.json`), JSON.stringify(session));
      const index = this.readIndex().filter((s) => s.id !== session.id);
      index.unshift(summarize(session));
      this.writeIndex(index);
    } catch {
      // History is a convenience; a failed write must never break a run.
    }
  }

  private readIndex(): SessionSummary[] {
    const dir = this.dir();
    if (!dir) return [];
    try {
      const raw = JSON.parse(fs.readFileSync(path.join(dir, "index.json"), "utf8"));
      return Array.isArray(raw) ? (raw as SessionSummary[]).filter((s) => s && ID_PATTERN.test(s.id)) : [];
    } catch {
      return [];
    }
  }

  private writeIndex(index: SessionSummary[]): void {
    const dir = this.dir();
    if (!dir) return;
    try {
      fs.mkdirSync(dir, { recursive: true });
      writeAtomic(path.join(dir, "index.json"), JSON.stringify(index, null, 1));
    } catch {
      // see writeSession
    }
  }

  private dir(): string | undefined {
    const root = this.root();
    return root ? path.join(root, ".qa-harness", "history") : undefined;
  }

  private file(id: string): string | undefined {
    const dir = this.dir();
    return dir && ID_PATTERN.test(id) ? path.join(dir, `${id}.json`) : undefined;
  }

  private changed(): void {
    for (const listener of this.listeners) {
      try {
        listener();
      } catch {
        // ignore listener failures
      }
    }
  }
}

function isLive(status: SessionStatus): boolean {
  return status === "running" || status === "waiting";
}

function signature(s: Session): string {
  return `${s.status}|${s.kind}|${s.steps}|${s.stage || ""}|${s.result ? s.result.passed + "/" + s.result.total : ""}`;
}

function summarize(session: Session): SessionSummary {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { events, ...summary } = session;
  return summary;
}

function writeAtomic(file: string, contents: string): void {
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, contents, "utf8");
  fs.renameSync(tmp, file);
}
