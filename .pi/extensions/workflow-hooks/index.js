import { createWorkflowGuard, scratchpadFor } from './core.mjs';

export default function workflowHooks(pi) {
  const guard = createWorkflowGuard();
  const scratchpad = ctx => scratchpadFor(ctx.cwd, ctx.sessionManager.getSessionId());

  // Pi dispatches these events for both direct tools and codemode's nested calls.
  // Handler errors fail closed on tool_call, rather than silently disabling a gate.
  pi.on('tool_call', (event, ctx) => guard.before(event, ctx.cwd, scratchpad(ctx)));
  pi.on('tool_result', (event, ctx) => guard.after(event, ctx.cwd, scratchpad(ctx)));
  pi.on('tool_execution_end', (event, ctx) => guard.ended(event, scratchpad(ctx)));
  // Also release a reservation if another extension denied a call or a run aborted.
  pi.on('agent_end', (_event, ctx) => guard.reset(scratchpad(ctx)));
  pi.on('session_start', (_event, ctx) => {
    if (ctx.hasUI) ctx.ui.setStatus('workflow-hooks', 'Project workflow hooks enabled');
  });
}
