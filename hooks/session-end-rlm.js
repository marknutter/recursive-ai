#!/usr/bin/env node
/**
 * RLM SessionEnd Hook - Archive conversation on session end
 *
 * Saves conversation transcript to episodic memory when session ends,
 * catching sessions that close without compaction.
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

function log(msg) {
  console.error(`[RLM-SessionEnd] ${msg}`);
}

function getProjectRoot() {
  try {
    const gitRoot = execSync('git rev-parse --show-toplevel', {
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe']
    }).trim();
    return gitRoot;
  } catch {
    return process.cwd();
  }
}

function getProjectName() {
  const root = getProjectRoot();
  return path.basename(root);
}

function getSessionFile() {
  const sessionsDir = path.join(os.homedir(), '.claude', 'sessions');

  if (!fs.existsSync(sessionsDir)) {
    return null;
  }

  // Find most recent .jsonl session file
  const files = fs.readdirSync(sessionsDir)
    .filter(f => f.endsWith('.jsonl'))
    .map(f => ({
      path: path.join(sessionsDir, f),
      mtime: fs.statSync(path.join(sessionsDir, f)).mtime
    }))
    .sort((a, b) => b.mtime - a.mtime);

  return files.length > 0 ? files[0].path : null;
}

function wasRecentlyArchived(sessionFile) {
  // Check if this session was archived in the last 60 seconds
  // (prevents duplicate archiving if both PreCompact and SessionEnd fire)
  const archiveMarker = sessionFile + '.rlm-archived';

  if (!fs.existsSync(archiveMarker)) {
    return false;
  }

  const stat = fs.statSync(archiveMarker);
  const ageSeconds = (Date.now() - stat.mtime.getTime()) / 1000;

  return ageSeconds < 60;
}

function markAsArchived(sessionFile) {
  // Touch a marker file to prevent duplicate archiving
  const archiveMarker = sessionFile + '.rlm-archived';
  fs.writeFileSync(archiveMarker, new Date().toISOString());
}

async function main() {
  try {
    const sessionFile = getSessionFile();

    if (!sessionFile) {
      log('No active session file found - skipping archive');
      process.exit(0);
    }

    // Skip if recently archived by PreCompact hook
    if (wasRecentlyArchived(sessionFile)) {
      log('Session already archived by PreCompact hook - skipping');
      process.exit(0);
    }

    const projectRoot = getProjectRoot();
    const projectName = getProjectName();
    const exportScript = path.join(projectRoot, 'examples', 'export_session.py');

    // Check if we're in the recursive-ai project with export script
    if (!fs.existsSync(exportScript)) {
      log('Export script not found - install RLM to enable episodic memory');
      process.exit(0);
    }

    log(`Archiving session on end...`);
    log(`Project: ${projectName}`);
    log(`Session: ${path.basename(sessionFile)}`);

    // Export session transcript
    const transcript = execSync(
      `uv run python "${exportScript}" "${sessionFile}"`,
      {
        encoding: 'utf8',
        cwd: projectRoot,
        stdio: ['pipe', 'pipe', 'pipe']
      }
    );

    if (!transcript || transcript.trim().length === 0) {
      log('Empty transcript - skipping archive');
      process.exit(0);
    }

    // Store in RLM memory
    const timestamp = new Date().toISOString().split('T')[0];
    const tags = `conversation,session,${projectName},${timestamp}`;
    const summary = `Conversation in ${projectName} on ${timestamp}`;

    execSync(
      `uv run rlm remember --stdin --tags "${tags}" --summary "${summary}"`,
      {
        input: transcript,
        encoding: 'utf8',
        cwd: projectRoot,
        stdio: ['pipe', 'pipe', 'pipe']
      }
    );

    // Mark as archived to prevent duplicate archiving
    markAsArchived(sessionFile);

    log(`✓ Session archived to ~/.rlm/memory/`);
    log(`  Tags: ${tags}`);
    log(`  Size: ${transcript.length.toLocaleString()} chars`);

  } catch (err) {
    log(`Error: ${err.message}`);
    // Don't fail session end if archiving fails
    process.exit(0);
  }
}

main().catch(err => {
  log(`Fatal error: ${err.message}`);
  process.exit(0);
});
