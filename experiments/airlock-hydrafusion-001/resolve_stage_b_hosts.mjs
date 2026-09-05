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
    path.resolve(
      process.env.AIRLOCK_REPO_ROOT,
      ".airlock/hydrafusion-001/task-freeze.json",
    ),
    "utf8",
  ),
);

class HostLimitationError extends Error {
  constructor(message) {
    super(message);
    this.name = "HostLimitationError";
  }
}

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

function errorText(error) {
  return String(error?.stack || error);
}

async function resolveCopilot() {
  const token = process.env.COPILOT_GITHUB_TOKEN;
  if (!token) {
    throw new Error(
      "COPILOT_GITHUB_TOKEN is required for Copilot runtime authentication",
    );
  }
  if (!process.env.COPILOT_HOME || !process.env.COPILOT_CLI_PATH) {
    throw new Error("COPILOT_HOME and COPILOT_CLI_PATH are required");
  }

  fs.mkdirSync(process.env.COPILOT_HOME, { recursive: true });
  fs.writeFileSync(
    path.join(process.env.COPILOT_HOME, "config.json"),
    JSON.stringify({ experimental: true }, null, 2) + "\n",
  );

  // GitHub Actions GITHUB_TOKEN is a server-to-server installation token.
  // Per GitHub's Copilot SDK auth contract, installation tokens MUST be
  // supplied to the child runtime environment, not the SDK gitHubToken field.
  const runtimeEnv = {
    ...process.env,
    COPILOT_GITHUB_TOKEN: token,
  };

  const client = new CopilotClient({
    baseDirectory: process.env.COPILOT_HOME,
    workingDirectory: process.env.AIRLOCK_REPO_ROOT,
    logLevel: "error",
    connection: RuntimeConnection.forStdio({
      path: process.env.COPILOT_CLI_PATH,
    }),
    env: runtimeEnv,
    useLoggedInUser: false,
  });

  try {
    await client.start();

    const models = await client.listModels();
    fs.writeFileSync(
      path.join(outDir, "copilot-models.json"),
      JSON.stringify(models, null, 2) + "\n",
    );

    const hydraMatches = models.filter((model) =>
      allStrings(model).some((value) => /hydrafusion/i.test(value))
    );
    const researchPreviewMatches = hydraMatches.filter((model) =>
      allStrings(model).some((value) => /research\s*preview/i.test(value))
    );

    let matches = researchPreviewMatches.length
      ? researchPreviewMatches
      : hydraMatches;

    if (matches.length === 0) {
      throw new HostLimitationError(
        "Copilot model metadata did not expose HydraFusion (Research Preview)",
      );
    }
    if (matches.length !== 1) {
      throw new HostLimitationError(
        `Copilot model metadata exposed ${matches.length} HydraFusion candidates; exact preview selection is ambiguous`,
      );
    }

    const model = matches[0];
    if (typeof model.id !== "string" || !model.id) {
      throw new HostLimitationError(
        "HydraFusion ModelInfo has no non-empty exact model id",
      );
    }

    // Validate that this exact ID can be selected programmatically, but do not
    // send a message. If the host cannot create this session noninteractively,
    // the frozen experiment requires INCONCLUSIVE_HOST_LIMITATION.
    let session;
    try {
      session = await client.createSession({
        model: model.id,
        workingDirectory: process.env.AIRLOCK_REPO_ROOT,
        enableSessionStore: false,
      });
    } catch (error) {
      throw new HostLimitationError(
        `HydraFusion exact model id ${model.id} cannot be selected noninteractively: ${errorText(error)}`,
      );
    }

    try {
      await session.disconnect();
    } catch (error) {
      throw new Error(
        `HydraFusion empty-session cleanup failed: ${errorText(error)}`,
      );
    }

    return {
      status: "PASS",
      cli_version: commandVersion("copilot"),
      resolved_model_id: model.id,
      model_info: model,
      metadata_source:
        "Copilot SDK listModels() with experimental=true and runtime-env installation-token auth",
      noninteractive_selection_without_prompt: true,
      task_prompt_sent: false,
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
    status: "PASS",
    cli_version: commandVersion("codex"),
    requested_model_id: requested,
    resolved_model_id: requested,
    metadata_source: "OpenAI /v1/models",
  };
}

async function resolveAnthropic() {
  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error(
      "ANTHROPIC_API_KEY repository secret is required for exact Opus metadata",
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

  // The frozen contract requires the Opus family, not a particular major
  // version. Resolve the newest exact Opus ID actually exposed by Anthropic.
  const opus = (payload.data || []).filter((row) =>
    typeof row.id === "string" && /^claude-opus(?:-|$)/.test(row.id)
  );
  if (!opus.length) {
    throw new Error("Anthropic metadata exposed no Claude Opus model");
  }

  opus.sort((a, b) => {
    const ta = Date.parse(a.created_at || 0) || 0;
    const tb = Date.parse(b.created_at || 0) || 0;
    if (tb !== ta) return tb - ta;
    return String(b.id).localeCompare(String(a.id));
  });

  return {
    status: "PASS",
    cli_version: commandVersion("claude"),
    requested_model_family: "Opus",
    resolved_model_id: opus[0].id,
    available_opus_ids: opus.map((row) => row.id),
    metadata_source: "Anthropic /v1/models",
  };
}

async function capture(result, key, resolver) {
  try {
    result[key] = await resolver();
    return null;
  } catch (error) {
    const kind =
      error instanceof HostLimitationError
        ? "HOST_LIMITATION"
        : "INFRASTRUCTURE_FAILURE";
    result[key] = {
      status: kind,
      error: errorText(error),
    };
    return { key, kind, error };
  }
}

async function main() {
  const result = {
    schema: "airlock.hydrafusion-001.stage-b-host-preflight.v2",
    experiment: "AIRLOCK-HYDRAFUSION-001",
    status: "STARTED",
    started_at: new Date().toISOString(),
    task_freeze_schema: freeze.schema,
    task_prompt_sha256: freeze.task.prompt_sha256,
    task_prompt_sent: false,
    worker_contact: false,
    resolved_order: freeze.stage_b.resolved_order,
    attempts_per_worker: freeze.stage_b.attempts_per_worker,
    note:
      "Metadata and empty-session selection only. All provider branches are checked before the run returns; no Stage B task prompt is submitted.",
  };

  // Always inspect all three branches so one repaired blocker does not merely
  // reveal another blocker on the next run.
  const failures = [];
  for (const [key, resolver] of [
    ["codex", resolveOpenAI],
    ["hydrafusion", resolveCopilot],
    ["opus", resolveAnthropic],
  ]) {
    const failure = await capture(result, key, resolver);
    if (failure) failures.push(failure);
  }

  const infrastructureFailures = failures.filter(
    (failure) => failure.kind === "INFRASTRUCTURE_FAILURE",
  );
  const hostLimitations = failures.filter(
    (failure) => failure.kind === "HOST_LIMITATION",
  );

  if (infrastructureFailures.length) {
    result.status = "STAGE_B_HOST_PREFLIGHT_INFRA_FAILURE";
    result.infrastructure_failures = infrastructureFailures.map(
      (failure) => failure.key,
    );
  } else if (hostLimitations.length) {
    // This is a completed scientific outcome under the frozen preregistration,
    // not broken CI. Stage B must stop before worker contact.
    result.status = "INCONCLUSIVE_HOST_LIMITATION";
    result.host_limitations = hostLimitations.map((failure) => failure.key);
  } else {
    result.status = "STAGE_B_HOST_PREFLIGHT_PASS";
  }

  result.task_prompt_sent = false;
  result.worker_contact = false;

  fs.writeFileSync(
    path.join(outDir, "host-preflight.json"),
    JSON.stringify(result, null, 2) + "\n",
  );

  console.log(result.status);
  for (const key of ["codex", "hydrafusion", "opus"]) {
    const row = result[key];
    const resolved = row?.resolved_model_id
      ? ` / ${row.resolved_model_id}`
      : "";
    console.log(`${key}: ${row?.status ?? "UNKNOWN"}${resolved}`);
  }

  return result.status === "STAGE_B_HOST_PREFLIGHT_INFRA_FAILURE" ? 2 : 0;
}

process.exitCode = await main();
