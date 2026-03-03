import { spawn } from "node:child_process";

type JsonRecord = Record<string, unknown>;

type PluginConfig = {
  enabled: boolean;
  bypassContinuity: boolean;
  apiBaseUrl: string;
  apiToken: string;
  tenantId: string;
  requestTimeoutMs: number;
  conversationPrefix: string;
  updateOnCompaction: boolean;
  updateOnReset: boolean;
  startupProbeAttempts: number;
  startupProbeDelayMs: number;
  healthPath: string;
  circuitBreakerFailureThreshold: number;
  circuitBreakerCooldownMs: number;
  autoStartApi: boolean;
  apiCommand: string;
  apiCommandArgs: string[];
  apiEnv: Record<string, string>;
};

type HookContext = {
  sessionId?: string;
  sessionKey?: string;
  agentId?: string;
};

type BeforeAgentStartEvent = {
  prompt?: string;
  messages?: unknown[];
};

type BeforeCompactionEvent = {
  messages?: unknown[];
};

type BeforeResetEvent = {
  messages?: unknown[];
};

type AgentEndEvent = {
  messages?: unknown[];
  success?: boolean;
};

type PluginApi = {
  pluginConfig?: unknown;
  logger: {
    info(message: string): void;
    warn(message: string): void;
    error(message: string): void;
  };
  registerService(service: {
    id: string;
    start: () => void | Promise<void>;
    stop?: () => void | Promise<void>;
  }): void;
  on(name: string, handler: (event: unknown, ctx: HookContext) => unknown): void;
};

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8080";
const DEFAULT_REQUEST_TIMEOUT_MS = 1500;
const DEFAULT_CONVERSATION_PREFIX = "cca-";
const DEFAULT_HEALTH_PATH = "/health";

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const out: string[] = [];
  for (const item of value) {
    if (typeof item === "string" && item.trim()) {
      out.push(item);
    }
  }
  return out;
}

function asStringMap(value: unknown): Record<string, string> {
  if (!isRecord(value)) {
    return {};
  }
  const out: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === "string") {
      out[key] = item;
    }
  }
  return out;
}

function normalizeConfig(raw: unknown): PluginConfig {
  const source = isRecord(raw) ? raw : {};
  return {
    enabled: asBoolean(source.enabled, true),
    bypassContinuity: asBoolean(source.bypassContinuity, false),
    apiBaseUrl: asString(source.apiBaseUrl, DEFAULT_API_BASE_URL).replace(/\/$/, ""),
    apiToken: asString(source.apiToken, ""),
    tenantId: asString(source.tenantId, "default"),
    requestTimeoutMs: Math.max(100, asNumber(source.requestTimeoutMs, DEFAULT_REQUEST_TIMEOUT_MS)),
    conversationPrefix: asString(source.conversationPrefix, DEFAULT_CONVERSATION_PREFIX),
    updateOnCompaction: asBoolean(source.updateOnCompaction, true),
    updateOnReset: asBoolean(source.updateOnReset, true),
    startupProbeAttempts: Math.max(1, Math.trunc(asNumber(source.startupProbeAttempts, 8))),
    startupProbeDelayMs: Math.max(100, Math.trunc(asNumber(source.startupProbeDelayMs, 500))),
    healthPath: asString(source.healthPath, DEFAULT_HEALTH_PATH),
    circuitBreakerFailureThreshold: Math.max(1, Math.trunc(asNumber(source.circuitBreakerFailureThreshold, 5))),
    circuitBreakerCooldownMs: Math.max(1000, Math.trunc(asNumber(source.circuitBreakerCooldownMs, 30000))),
    autoStartApi: asBoolean(source.autoStartApi, false),
    apiCommand: asString(source.apiCommand, ""),
    apiCommandArgs: asStringList(source.apiCommandArgs),
    apiEnv: asStringMap(source.apiEnv),
  };
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function toConversationId(prefix: string, ctx: HookContext): string {
  const raw = ctx.sessionId || ctx.sessionKey || ctx.agentId || "default";
  const safe = raw.replace(/[^A-Za-z0-9._-]/g, "-");
  return `${prefix}${safe}`;
}

function parseMessageText(message: unknown): string {
  if (typeof message === "string") {
    return message.trim();
  }
  if (!isRecord(message)) {
    return "";
  }

  if (typeof message.text === "string") {
    return message.text.trim();
  }

  const content = message.content;
  if (typeof content === "string") {
    return content.trim();
  }
  if (Array.isArray(content)) {
    const parts: string[] = [];
    for (const item of content) {
      if (!isRecord(item)) {
        continue;
      }
      if (typeof item.text === "string" && item.text.trim()) {
        parts.push(item.text.trim());
      }
    }
    return parts.join(" ").trim();
  }
  return "";
}

function parseMessageRole(message: unknown): string {
  if (!isRecord(message)) {
    return "message";
  }
  const role = message.role;
  if (typeof role === "string" && role.trim()) {
    return role.trim().toLowerCase();
  }
  return "message";
}

function extractTurns(messages: unknown[] | undefined): string[] {
  if (!Array.isArray(messages)) {
    return [];
  }
  const turns: string[] = [];
  for (const msg of messages) {
    const text = parseMessageText(msg);
    if (!text) {
      continue;
    }
    const role = parseMessageRole(msg);
    turns.push(`${role}:${text}`);
  }
  return turns;
}

function extractLastAssistantText(messages: unknown[] | undefined): string {
  if (!Array.isArray(messages)) {
    return "";
  }
  for (let idx = messages.length - 1; idx >= 0; idx -= 1) {
    const msg = messages[idx];
    if (parseMessageRole(msg) !== "assistant") {
      continue;
    }
    const text = parseMessageText(msg);
    if (text) {
      return text;
    }
  }
  return "";
}

async function postJson(
  baseUrl: string,
  endpoint: string,
  payload: JsonRecord,
  timeoutMs: number,
  token: string,
  tenantId: string,
  logger: PluginApi["logger"],
): Promise<JsonRecord | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${baseUrl}${endpoint}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(tenantId ? { "X-Tenant-Id": tenantId } : {}),
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      const body = await response.text();
      logger.warn(`[continuity-anchor] ${endpoint} failed (${response.status}): ${body}`);
      return null;
    }

    const data = await response.json();
    return isRecord(data) ? data : null;
  } catch (error) {
    logger.warn(`[continuity-anchor] ${endpoint} request error: ${toErrorMessage(error)}`);
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function startAnchorApi(config: PluginConfig, logger: PluginApi["logger"]) {
  if (!config.autoStartApi) {
    return null;
  }
  if (!config.apiCommand) {
    logger.warn("[continuity-anchor] autoStartApi=true but apiCommand is empty");
    return null;
  }

  const child = spawn(config.apiCommand, config.apiCommandArgs, {
    env: {
      ...process.env,
      ...config.apiEnv,
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  child.stdout.on("data", (chunk) => {
    const line = chunk.toString("utf-8").trim();
    if (line) {
      logger.info(`[continuity-anchor][api] ${line}`);
    }
  });

  child.stderr.on("data", (chunk) => {
    const line = chunk.toString("utf-8").trim();
    if (line) {
      logger.warn(`[continuity-anchor][api][stderr] ${line}`);
    }
  });

  child.on("exit", (code, signal) => {
    logger.warn(`[continuity-anchor] anchor api process exited code=${String(code)} signal=${String(signal)}`);
  });

  logger.info(`[continuity-anchor] started anchor api via: ${config.apiCommand}`);
  return child;
}

async function healthProbe(config: PluginConfig, logger: PluginApi["logger"]): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.requestTimeoutMs);
  try {
    const response = await fetch(`${config.apiBaseUrl}${config.healthPath}`, {
      method: "GET",
      headers: {
        ...(config.apiToken ? { Authorization: `Bearer ${config.apiToken}` } : {}),
        ...(config.tenantId ? { "X-Tenant-Id": config.tenantId } : {}),
      },
      signal: controller.signal,
    });
    if (response.ok) {
      return true;
    }
    logger.warn(`[continuity-anchor] health probe failed (${response.status})`);
    return false;
  } catch (error) {
    logger.warn(`[continuity-anchor] health probe error: ${toErrorMessage(error)}`);
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function startupProbe(config: PluginConfig, logger: PluginApi["logger"]): Promise<boolean> {
  for (let attempt = 1; attempt <= config.startupProbeAttempts; attempt += 1) {
    const ok = await healthProbe(config, logger);
    if (ok) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, config.startupProbeDelayMs));
  }
  return false;
}

export default function register(api: PluginApi): void {
  const config = normalizeConfig(api.pluginConfig);
  const turnCounters = new Map<string, number>();
  let apiProcess: ReturnType<typeof startAnchorApi> = null;
  let failureStreak = 0;
  let circuitOpenUntil = 0;

  const isBypassed = (): boolean => {
    if (!config.enabled || config.bypassContinuity) {
      return true;
    }
    return Date.now() < circuitOpenUntil;
  };

  const onCallFailure = (): void => {
    failureStreak += 1;
    if (failureStreak >= config.circuitBreakerFailureThreshold) {
      circuitOpenUntil = Date.now() + config.circuitBreakerCooldownMs;
      api.logger.warn(
        `[continuity-anchor] circuit opened for ${config.circuitBreakerCooldownMs}ms after ${failureStreak} failures`,
      );
    }
  };

  const onCallSuccess = (): void => {
    failureStreak = 0;
    circuitOpenUntil = 0;
  };

  api.registerService({
    id: "continuity-anchor-api",
    start: async () => {
      if (!config.enabled || config.bypassContinuity) {
        api.logger.warn("[continuity-anchor] service start bypassed by config");
        return;
      }
      apiProcess = startAnchorApi(config, api.logger);
      const ready = await startupProbe(config, api.logger);
      if (!ready) {
        onCallFailure();
        api.logger.warn("[continuity-anchor] startup probe failed; continuity hooks will bypass until recovery");
        return;
      }
      onCallSuccess();
    },
    stop: async () => {
      if (apiProcess !== null) {
        apiProcess.kill("SIGTERM");
        apiProcess = null;
      }
    },
  });

  api.on("before_agent_start", async (rawEvent, ctx) => {
    if (isBypassed()) {
      return;
    }
    const event = isRecord(rawEvent) ? (rawEvent as BeforeAgentStartEvent) : {};
    const conversationId = `${config.tenantId}:${toConversationId(config.conversationPrefix, ctx)}`;
    const latestTurns = extractTurns(event.messages);
    if (latestTurns.length > 0) {
      const updateRes = await postJson(
        config.apiBaseUrl,
        "/anchor/update",
        {
          conversation_id: conversationId,
          latest_turns: latestTurns,
          optional_event: "before_response",
          force: false,
        },
        config.requestTimeoutMs,
        config.apiToken,
        config.tenantId,
        api.logger,
      );
      if (updateRes === null) {
        onCallFailure();
      } else {
        onCallSuccess();
      }
    }

    const prompt = asString(event.prompt, "").trim();
    if (!prompt) {
      return;
    }

    const contextPayload = await postJson(
      config.apiBaseUrl,
      "/anchor/render-context",
      {
        conversation_id: conversationId,
        user_query: prompt,
      },
      config.requestTimeoutMs,
      config.apiToken,
      config.tenantId,
      api.logger,
    );
    if (!contextPayload) {
      onCallFailure();
      return;
    }
    onCallSuccess();

    const block = asString(contextPayload.continuity_context_block, "").trim();
    if (!block) {
      return;
    }

    return {
      prependContext: block,
    };
  });

  api.on("before_compaction", async (rawEvent, ctx) => {
    if (isBypassed()) {
      return;
    }
    if (!config.updateOnCompaction) {
      return;
    }
    const event = isRecord(rawEvent) ? (rawEvent as BeforeCompactionEvent) : {};
    const latestTurns = extractTurns(event.messages);
    if (latestTurns.length === 0) {
      return;
    }

    const response = await postJson(
      config.apiBaseUrl,
      "/anchor/update",
      {
        conversation_id: `${config.tenantId}:${toConversationId(config.conversationPrefix, ctx)}`,
        latest_turns: latestTurns,
        optional_event: "before_compaction",
        force: true,
      },
      config.requestTimeoutMs,
      config.apiToken,
      config.tenantId,
      api.logger,
    );
    if (response === null) {
      onCallFailure();
      return;
    }
    onCallSuccess();
  });

  api.on("before_reset", async (rawEvent, ctx) => {
    if (isBypassed()) {
      return;
    }
    if (!config.updateOnReset) {
      return;
    }
    const event = isRecord(rawEvent) ? (rawEvent as BeforeResetEvent) : {};
    const latestTurns = extractTurns(event.messages);
    if (latestTurns.length === 0) {
      return;
    }

    const response = await postJson(
      config.apiBaseUrl,
      "/anchor/update",
      {
        conversation_id: `${config.tenantId}:${toConversationId(config.conversationPrefix, ctx)}`,
        latest_turns: latestTurns,
        optional_event: "before_reset",
        force: true,
      },
      config.requestTimeoutMs,
      config.apiToken,
      config.tenantId,
      api.logger,
    );
    if (response === null) {
      onCallFailure();
      return;
    }
    onCallSuccess();
  });

  api.on("agent_end", async (rawEvent, ctx) => {
    if (isBypassed()) {
      return;
    }
    const event = isRecord(rawEvent) ? (rawEvent as AgentEndEvent) : {};
    if (event.success === false) {
      return;
    }

    const responseText = extractLastAssistantText(event.messages);
    if (!responseText) {
      return;
    }

    const conversationId = `${config.tenantId}:${toConversationId(config.conversationPrefix, ctx)}`;
    const nextTurnId = (turnCounters.get(conversationId) || 0) + 1;
    turnCounters.set(conversationId, nextTurnId);

    const response = await postJson(
      config.apiBaseUrl,
      "/anchor/ack-response",
      {
        conversation_id: conversationId,
        response_text: responseText,
        turn_id: nextTurnId,
      },
      config.requestTimeoutMs,
      config.apiToken,
      config.tenantId,
      api.logger,
    );
    if (response === null) {
      onCallFailure();
      return;
    }
    onCallSuccess();
  });

  api.logger.info("[continuity-anchor] plugin initialized");
}
