# OpenClaw Continuity Anchor Plugin

This folder is a drop-in OpenClaw plugin scaffold that enables continuity context by default, without running a separate wrapper command for every user request.

## Directory Layout

```
openclaw-continuity-plugin/
  index.ts
  openclaw.plugin.json
  openclaw.yaml.example
```

## What This Plugin Does

- `before_agent_start`: renders continuity context from `/anchor/render-context` and prepends it into the prompt.
- `before_compaction`: forces an anchor update before `/compact` via `/anchor/update`.
- `before_reset`: forces an anchor update before `/reset` via `/anchor/update`.
- `agent_end`: acknowledges assistant response with `/anchor/ack-response`.

The plugin is fail-open: if continuity API is unavailable, OpenClaw still responds normally.

Operational controls:

- `enabled`: master plugin switch
- `bypassContinuity`: fast bypass switch (keeps plugin loaded, skips API calls)
- startup probe + circuit breaker (`startupProbe*`, `circuitBreaker*`) to avoid repeated failure loops

Note: `before_agent_start` is used for compatibility and simple context injection. If your OpenClaw version recommends split hooks, you can move logic to `before_prompt_build` (context injection) and `before_model_resolve` (model/provider override).

## API Contract Assumed

The plugin aligns to the current continuity API in this repo:

- `POST /anchor/update`
- `POST /anchor/render-context`
- `POST /anchor/ack-response`

## Installation Into OpenClaw

1. Copy this folder into OpenClaw extensions path, for example:

   - source: `assets/openclaw-continuity-plugin`
   - destination: `/opt/openclaw/extensions/continuity-anchor`

2. Merge `openclaw.yaml.example` content into your OpenClaw config (`openclaw.yaml`).

   - If OpenClaw already has a memory plugin in `plugins.slots.memory`, switch that slot to `continuity-anchor`.

3. Adjust values:

   - `tenantId` for conversation namespace
   - `apiToken` to match server `--api-token <token>:<tenant>` mapping
   - `apiBaseUrl` if API is not on localhost:8080
   - `apiCommandArgs` paths for your continuity-memory checkout
   - TiDB credential file path

4. Restart OpenClaw.

## Auto-Start Behavior

If `autoStartApi: true`, the plugin starts the continuity API process using:

- `apiCommand`
- `apiCommandArgs`
- optional extra env via `apiEnv`

If you run anchor API as a separate service, set `autoStartApi: false` and keep `apiBaseUrl` pointing to that service.
