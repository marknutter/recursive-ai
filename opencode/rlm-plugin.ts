/**
 * RLM Plugin for OpenCode
 *
 * Provides persistent memory integration via three hooks:
 * 1. System prompt injection — context from previous sessions
 * 2. Session compacting — archive before compaction
 * 3. Session idle — archive when agent stops responding
 *
 * This is a thin JS/TS bridge that shells out to the Python CLI.
 */
import type { Plugin } from "@opencode-ai/plugin";

// Substituted by install-opencode.sh — absolute path to the RLM project root
const RLM_ROOT = "__RLM_ROOT__";

// Cache duration for system context injection (5 minutes)
const CONTEXT_CACHE_TTL_MS = 5 * 60 * 1000;

// Dedup guard: skip archival if same session archived within 60 seconds
const ARCHIVE_DEDUP_WINDOW_MS = 60 * 1000;

export const RlmPlugin: Plugin = async ({ $, directory }) => {
  // --- State ---
  let cachedContext: string | null = null;
  let contextCachedAt = 0;
  const archiveTimestamps = new Map<string, number>();

  /**
   * Run an RLM CLI command and return stdout.
   * Uses uv run to ensure the correct Python environment.
   */
  async function rlm(...args: string[]): Promise<string> {
    const result = await $`uv run --project ${RLM_ROOT} rlm ${args}`.text();
    return result.trim();
  }

  /**
   * Get the project name from the current directory for tag filtering.
   */
  function getProjectTag(): string {
    const parts = directory.split("/");
    return parts[parts.length - 1] || "unknown";
  }

  /**
   * Check if we should skip archival (dedup guard).
   */
  function shouldSkipArchival(sessionId: string): boolean {
    const lastArchived = archiveTimestamps.get(sessionId);
    if (lastArchived && Date.now() - lastArchived < ARCHIVE_DEDUP_WINDOW_MS) {
      return true;
    }
    return false;
  }

  /**
   * Archive an OpenCode session via the CLI.
   */
  async function archiveSession(sessionId: string): Promise<void> {
    if (shouldSkipArchival(sessionId)) {
      return;
    }

    try {
      // Use opencode CLI to export the session, then pipe to rlm archive
      const exportJson = await $`opencode session export ${sessionId}`
        .quiet()
        .nothrow()
        .text();

      if (!exportJson.trim()) {
        return;
      }

      // Write to temp file and archive
      const tmpFile = `/tmp/rlm-opencode-${sessionId}.json`;
      await Bun.write(tmpFile, exportJson);

      await $`uv run --project ${RLM_ROOT} rlm archive-opencode ${tmpFile} --cwd ${directory}`
        .quiet()
        .nothrow();

      // Clean up temp file
      await $`rm -f ${tmpFile}`.quiet().nothrow();

      archiveTimestamps.set(sessionId, Date.now());
    } catch {
      // Non-fatal — don't crash the session
    }
  }

  return {
    /**
     * Inject RLM context into the system prompt.
     * Cached for 5 minutes to avoid re-running on every message.
     */
    "experimental.chat.system.transform": async ({ output }) => {
      try {
        const now = Date.now();
        if (!cachedContext || now - contextCachedAt > CONTEXT_CACHE_TTL_MS) {
          const project = getProjectTag();
          cachedContext = await rlm(
            "memory-list",
            "--tags",
            `conversation,${project}`,
            "--limit",
            "10",
          );
          contextCachedAt = now;
        }

        if (cachedContext) {
          output.system.push(
            `\n## RLM Memory Context\nRelevant memories from previous sessions:\n\n${cachedContext}`,
          );
        }
      } catch {
        // Non-fatal — context injection is best-effort
      }
    },

    /**
     * Archive session before compaction.
     */
    "experimental.session.compacting": async ({ input }) => {
      const sessionId = input.sessionID || input.session_id;
      if (sessionId) {
        await archiveSession(sessionId);
      }
    },

    /**
     * Archive session when agent goes idle (with dedup guard).
     */
    event: async ({ event }) => {
      if (event.type === "session.idle") {
        const sessionId =
          (event as any).sessionID || (event as any).session_id;
        if (sessionId) {
          await archiveSession(sessionId);
        }
      }
    },
  };
};
