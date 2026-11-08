/**
 * Line-delimited JSON-RPC 2.0 Client over ChildProcess stdio streams.
 * Opens NO local network listeners or TCP sockets.
 */

import { Readable, Writable } from "stream";
import { EventEmitter } from "events";
import {
  RPCRequest,
  RPCResponse,
  RPCNotification,
  RPCError,
} from "./protocol";

export type RequestHandler = (params: Record<string, unknown>) => Promise<unknown>;

export class RPCClient extends EventEmitter {
  private nextId = 1;
  private readonly requestHandlers = new Map<string, RequestHandler>();
  private pendingRequests = new Map<
    string | number,
    {
      resolve: (result: unknown) => void;
      reject: (error: Error | RPCError) => void;
      timeout: NodeJS.Timeout;
    }
  >();
  private buffer = "";

  constructor(
    private readonly stdinStream: Writable,
    private readonly stdoutStream: Readable,
    private readonly defaultTimeoutMs: number = 30000
  ) {
    super();
    this.setupReader();
  }

  private setupReader(): void {
    this.stdoutStream.on("data", (chunk: Buffer) => {
      this.buffer += chunk.toString("utf-8");
      this.processBuffer();
    });

    this.stdoutStream.on("end", () => {
      this.rejectAllPending(new Error("RPC channel closed by remote process"));
    });

    this.stdoutStream.on("error", (err: Error) => {
      this.rejectAllPending(err);
    });
  }

  private processBuffer(): void {
    const lines = this.buffer.split("\n");
    // The last element is either empty (if ended with newline) or partial
    this.buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      this.handleIncomingLine(trimmed);
    }
  }

  private handleIncomingLine(line: string): void {
    try {
      const parsed = JSON.parse(line);

      // Check if response
      if ("id" in parsed && parsed.id !== null && this.pendingRequests.has(parsed.id)) {
        const response = parsed as RPCResponse;
        const pending = this.pendingRequests.get(response.id!);
        if (pending) {
          clearTimeout(pending.timeout);
          this.pendingRequests.delete(response.id!);
          if (response.error) {
            pending.reject(response.error);
          } else {
            pending.resolve(response.result);
          }
        }
        return;
      }

      // Engine -> extension request (e.g. llm.chat, secrets.resolve)
      if ("method" in parsed && "id" in parsed && parsed.id !== null) {
        void this.handleIncomingRequest(parsed as RPCRequest);
        return;
      }

      // Check if notification
      if ("method" in parsed && !("id" in parsed && parsed.id !== null)) {
        const notification = parsed as RPCNotification;
        this.emit("notification", notification);
        this.emit(`notify:${notification.method}`, notification.params || {});
        return;
      }
    } catch (e) {
      this.emit("error", new Error(`Failed to parse RPC line: ${e}`));
    }
  }

  public onRequest(method: string, handler: RequestHandler): void {
    this.requestHandlers.set(method, handler);
  }

  private async handleIncomingRequest(request: RPCRequest): Promise<void> {
    const handler = this.requestHandlers.get(request.method);
    let reply: RPCResponse;
    if (!handler) {
      reply = {
        jsonrpc: "2.0",
        id: request.id,
        error: { code: -32601, message: `Method not found: '${request.method}'` },
      };
    } else {
      try {
        reply = { jsonrpc: "2.0", id: request.id, result: await handler(request.params || {}) };
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        reply = { jsonrpc: "2.0", id: request.id, error: { code: -32000, message } };
      }
    }
    this.stdinStream.write(JSON.stringify(reply) + "\n", "utf-8");
  }

  public sendRequest<T = unknown>(
    method: string,
    params: Record<string, unknown> = {},
    timeoutMs?: number
  ): Promise<T> {
    const id = this.nextId++;
    const request: RPCRequest = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    };

    return new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id);
          reject(new Error(`RPC request '${method}' timed out after ${timeoutMs || this.defaultTimeoutMs}ms`));
        }
      }, timeoutMs || this.defaultTimeoutMs);

      this.pendingRequests.set(id, {
        resolve: resolve as (result: unknown) => void,
        reject,
        timeout,
      });

      const payload = JSON.stringify(request) + "\n";
      this.stdinStream.write(payload, "utf-8", (err) => {
        if (err) {
          clearTimeout(timeout);
          this.pendingRequests.delete(id);
          reject(err);
        }
      });
    });
  }

  public sendNotification(method: string, params: Record<string, unknown> = {}): void {
    const notification: RPCNotification = {
      jsonrpc: "2.0",
      method,
      params,
    };
    const payload = JSON.stringify(notification) + "\n";
    this.stdinStream.write(payload, "utf-8");
  }

  public rejectAllPending(err: Error): void {
    for (const [id, pending] of this.pendingRequests.entries()) {
      clearTimeout(pending.timeout);
      pending.reject(err);
    }
    this.pendingRequests.clear();
  }
}

