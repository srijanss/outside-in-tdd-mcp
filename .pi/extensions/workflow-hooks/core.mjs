import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export function scratchpadFor(cwd, sessionId) {
  const key = createHash('sha256').update(`${cwd}\0${sessionId}`).digest('hex');
  return join(tmpdir(), `project-mcp-pi-${key}`);
}

export function hookInput(event, cwd, scratchpad) {
  const names = { bash: 'Bash', read: 'Read', edit: 'Edit', write: 'Write' };
  let name = names[event.toolName] ?? event.toolName;
  name = name.replace(/^mcp__outside_in_tdd__/, 'mcp__outside-in-tdd__')
    .replace(/^mcp__project_mcp__/, 'mcp__project-mcp__');
  const input = { ...event.input };
  if (input.path !== undefined) input.file_path = input.path;
  // Pi's extra search tools must not bypass the shared cold-exploration gate.
  if (['grep', 'find'].includes(event.toolName)) {
    name = 'Bash';
    input.command = event.toolName === 'grep' ? 'rg' : 'find';
  }
  return {
    tool_name: name,
    tool_input: input,
    tool_response: event.structuredContent ?? { content: event.content, isError: event.isError },
    scratchpad_dir: scratchpad,
    cwd,
  };
}

export function isTddMutation(name) {
  return /^mcp__outside[-_]in[-_]tdd__/.test(name) &&
    !/__(get_status|list_features|list_review_findings|list_research|search_research)$/.test(name);
}

export function successfulResult(event) {
  if (event.isError || event.structuredContent?.isError) return false;
  // Some MCP servers return a nested CallToolResult rather than throwing.
  for (const block of event.content ?? []) {
    if (block.type !== 'text') continue;
    try { if (JSON.parse(block.text).isError === true) return false; } catch { /* plain text */ }
  }
  return true;
}

function runCommand(command, payload, cwd, timeoutMs) {
  return new Promise((resolve, reject) => {
    const child = spawn('/bin/bash', ['-c', command], {
      cwd,
      env: { ...process.env, CLAUDE_PROJECT_DIR: cwd },
      stdio: ['pipe', 'pipe', 'pipe'],
      detached: true,
    });
    let stdout = '', stderr = '', failure;
    const stop = reason => {
      failure = reason;
      // Kill the hook's process group too, not only its parent shell.
      try { process.kill(-child.pid, 'SIGKILL'); } catch { child.kill('SIGKILL'); }
    };
    const timer = setTimeout(() => stop('hook timed out'), timeoutMs);
    child.stdout.on('data', chunk => {
      stdout += chunk;
      if (stdout.length > 65536) stop('hook output exceeds 64 KiB');
    });
    child.stderr.on('data', chunk => {
      stderr += chunk;
      if (stderr.length > 65536) stop('hook output exceeds 64 KiB');
    });
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', code => {
      clearTimeout(timer);
      if (failure) reject(new Error(failure));
      else resolve({ code, stdout, stderr });
    });
    child.stdin.on('error', () => {}); // A hook can exit before consuming input.
    child.stdin.end(JSON.stringify(payload));
  });
}

export async function runHooks(stage, event, cwd, scratchpad, timeoutMs = 10000) {
  // Deliberately project-only: do not run a second copy of global Claude hooks.
  const settings = JSON.parse(await readFile(join(cwd, '.claude/settings.json'), 'utf8'));
  const payload = hookInput(event, cwd, scratchpad);
  await mkdir(scratchpad, { recursive: true, mode: 0o700 });
  for (const group of settings.hooks?.[stage] ?? []) {
    if (group.matcher && !new RegExp(`^(?:${group.matcher})$`).test(payload.tool_name)) continue;
    for (const hook of group.hooks ?? []) {
      if (hook.type !== 'command') throw new Error(`Unsupported hook type: ${hook.type}`);
      const result = await runCommand(hook.command, payload, cwd, timeoutMs);
      if (result.code !== 0) {
        return { block: true, reason: result.stderr.trim() || `Hook exited ${result.code}` };
      }
      if (!result.stdout.trim()) continue;
      const output = JSON.parse(result.stdout);
      if (output.decision === 'block' || output.hookSpecificOutput?.permissionDecision === 'deny') {
        return {
          block: true,
          reason: output.hookSpecificOutput?.permissionDecisionReason ?? output.reason ?? 'Blocked by project hook',
        };
      }
    }
  }
}

export function createWorkflowGuard() {
  let queue = Promise.resolve();
  const active = new Map();
  const serialized = work => {
    const next = queue.then(work);
    queue = next.catch(() => {});
    return next;
  };
  return {
    before(event, cwd, scratchpad) {
      return serialized(async () => {
        if (isTddMutation(event.toolName) && active.has(scratchpad)) {
          return { block: true, reason: 'A TDD state-changing call is still running. Await it before the next call.' };
        }
        const result = await runHooks('PreToolUse', event, cwd, scratchpad);
        if (!result?.block && isTddMutation(event.toolName)) active.set(scratchpad, event.toolCallId);
        return result;
      });
    },
    after(event, cwd, scratchpad) {
      return serialized(async () => {
        try {
          if (successfulResult(event)) {
            const result = await runHooks('PostToolUse', event, cwd, scratchpad);
            if (result?.block) throw new Error(result.reason);
          }
        } finally {
          if (active.get(scratchpad) === event.toolCallId) active.delete(scratchpad);
        }
      });
    },
    ended(event, scratchpad) {
      if (active.get(scratchpad) === event.toolCallId) active.delete(scratchpad);
    },
    reset(scratchpad) {
      active.delete(scratchpad);
    },
  };
}
