#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { CopilotClient, RuntimeConnection } from "@github/copilot-sdk";

const outDir = process.argv[2];
if (!outDir) {
  console.error("usage: resolve_stage_b_hosts.mjs OUT_DIR");
  process.exit(2);
}
fs.mkdirSync(outDir, { recursive: true });

const freeze = JSON.parse(
  fs.readFileSync(
    path.resolve(process.env.AIRLOCK_REPO_ROOT, ".airlock/hydrafusion-001/task-freeze.json"),
    "utf8",
  ),
);

function commandVersion(command) {
  return execFileSync(command, ["--version"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim().split(/\r?\n/)[0];
}

async function fetchJson(url, headers) {
  const response = await fetch(url, { headers });
  const body = await response.text();
  if (!response.ok) {
    throw new Error(`${url} -> HTTP ${response.status}: ${body.slice(0, 500)}`);
  }
  return JSON.parse(body);
}

function allStrings(value) {
  const out = [];
  if (typeof value === "string") {
    out.push(value);
  } else if (Array.isArray(value)) {
    value.forEach((item) => out.push(...allStrings(item)));
  } else if (value && typeof value === "object") {
    Object.values(value).forEach((item) => out.push(...allStrings(item)));
  }
  return out;
}

async function resolveCopilot() {
  if (!process.env.GITHUB_TOKEN) {
    throw new Error("GITHUB_TOKEN is required for Copilot model metadata");
  }
  if (!process.env.COPILOT_HOME || !process.env.COPILOT_CLI_PATH) {
    throw new Error("COPILOT_HOME and COPILOT_CLI_PATH are required");
  }

  fs.mkdirSync(process.env.COPILOT_HOME, { recursive: true });
  fs.writeFileSync(
    path.join(process.env.COPILOT_HOME, "config.json"),
    JSON.stringify({ experimental: true }, null, 2) + "\n",
  );

  const client = new CopilotClient({
    baseDirectory: process.env.COPILOT_HOME,
    workingDirectory: process.env.AIRLOCK_REPO_ROOT,
    logLevel: "error",
    connection: RuntimeConnection.forStdio({ path: process.env.COPILOT_CLI_PATH }),
    gitHubToken: process.env.GITHUB_TOKEN,
  });

  try {
    await client.start();
    const models = await client.listModels();
    fs.writeFileSync(
      path.join(outDir, "copilot-models.json"),
      JSON.stringify(models, null, 2) + "\n",
    );

    const matches = models.filter((model) =>
      allStrings(model).some((value) => /hydrafusion/i.test(value))
    );
    if (matches.length !== 1) {
      throw new Error(
        `expected exactly one HydraFusion model from Copilot listModels(), found ${matches.length}`
      );
    }

    const model = matches[0];
    if (typeof model.id !== "string" || !model.id) {
      throw new Error("HydraFusion ModelInfo has no non-empty id");
    }

    // Prove exact model selection without submitting any message.
    const session = await client.createSession({
      model: model.id,
      workingDirectory: process.env.AIRLOCK_REPO_ROOT,
      enableSessionStore: false,
    });
    await session.disconnect();

    return {
      cli_version: commandVersion("copilot"),
      resolved_model_id: model.id,
      model_info: model,
      metadata_source: "Copilot SDK listModels() with experimental=true",
      noninteractive_selection_without_prompt: true,
    };
  } finally {
    await client.stop().catch(() => {});
  }
}

async function resolveOpenAI() {
  if (!process.env.OPENAI_API_KEY) {
    throw new Error("OPENAI_API_KEY repository secret is required");
  }

  const requested = freeze.host_launch_contracts.codex.requested_model;
  const payload = await fetchJson(
    "https://api.openai.com/v1/models",
    { Authorization: `Bearer ${process.env.OPENAI_API_KEY}` },
  );
  fs.writeFileSync(
    path.join(outDir, "openai-models.json"),
    JSON.stringify(payload, null, 2) + "\n",
  );

  const ids = (payload.data || []).map((row) => row.id);
  if (!ids.includes(requested)) {
    throw new Error(`OpenAI metadata did not expose frozen model ${requested}`);
  }

  return {
    cli_version: commandVersion("codex"),
    requested_model_id: requested,
    resolved_model_id: requested,
    metadata_source: "OpenAI /v1/models",
  };
}

async function resolveAnthropic() {
  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error(
      "ANTHROPIC_API_KEY repository secret is required for exact Opus metadata"
    );
  }

  const payload = await fetchJson(
    "https://api.anthropic.com/v1/models?limit=100",
    {
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
    },
  );
  fs.writeFileSync(
    path.join(outDir, "anthropic-models.json"),
    JSON.stringify(payload, null, 2) + "\n",
  );

  const opus = (payload.data || []).filter((row) =>
    typeof row.id === "string" && /^claude-opus-5(?:-|$)/.test(row.id)
  );
  if (!opus.length) {
    throw new Error("Anthropic metadata exposed no Claude Opus 5 model");
  }

  opus.sort((a, b) => {
    const ta = Date.parse(a.created_at || 0) || 0;
    const tb = Date.parse(b.created_at || 0) || 0;
    if (tb !== ta) return tb - ta;
    return String(b.id).localeCompare(String(a.id));
  });

  return {
    cli_version: commandVersion("claude"),
    requested_model_family: "Opus",
    resolved_model_id: opus[0].id,
    available_opus_5_ids: opus.map((row) => row.id),
    metadata_source: "Anthropic /v1/models",
  };
}

async function main() {
  const result = {
    schema: "airlock.hydrafusion-001.stage-b-host-preflight.v1",
    experiment: "AIRLOCK-HYDRAFUSION-001",
    status: "STARTED",
    started_at: new Date().toISOString(),
    task_freeze_schema: freeze.schema,
    task_prompt_sha256: freeze.task.prompt_sha256,
    task_prompt_sent: false,
    worker_contact: false,
    note: "Metadata/session-selection preflight only; no Stage B task prompt is submitted.",
  };

  try {
    result.codex = await resolveOpenAI();
    result.hydrafusion = await resolveCopilot();
    result.opus = await resolveAnthropic();

    if (result.codex.resolved_model_id !== "gpt-5.6-sol") {
      throw new Error("Codex resolved model differs from frozen gpt-5.6-sol");
    }
    if (!/hydrafusion/i.test(JSON.stringify(result.hydrafusion.model_info))) {
      throw new Error("resolved Copilot model does not identify as HydraFusion");
    }
    if (!/^claude-opus-5(?:-|$)/.test(result.opus.resolved_model_id)) {
      throw new Error("resolved Claude model is outside frozen Opus family");
    }

    result.status = "STAGE_B_HOST_PREFLIGHT_PASS";
    result.resolved_order = freeze.stage_b.resolved_order;
    result.attempts_per_worker = freeze.stage_b.attempts_per_worker;

    fs.writeFileSync(
      path.join(outDir, "host-preflight.json"),
      JSON.stringify(result, null, 2) + "\n",
    );

    console.log("STAGE_B_HOST_PREFLIGHT_PASS");
    console.log(`Codex: ${result.codex.cli_version} / ${result.codex.resolved_model_id}`);
    console.log(
      `HydraFusion: ${result.hydrafusion.cli_version} / ${result.hydrafusion.resolved_model_id}`
    );
    console.log(`Opus: ${result.opus.cli_version} / ${result.opus.resolved_model_id}`);
    return 0;
  } catch (error) {
    result.status = "STAGE_B_HOST_PREFLIGHT_BLOCKED";
    result.error = String(error?.stack || error);
    result.task_prompt_sent = false;
    result.worker_contact = false;

    fs.writeFileSync(
      path.join(outDir, "host-preflight.json"),
      JSON.stringify(result, null, 2) + "\n",
    );
    console.error(result.error);
    return 2;
  }
}

process.exitCode = await main();
