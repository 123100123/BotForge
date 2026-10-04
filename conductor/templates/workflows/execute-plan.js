export const meta = {
  name: 'execute-plan',
  description: 'Run a conductor plan: role agents execute units in parallel worktrees, escalate once on failure, then integrate and verify',
  whenToUse: 'XL-class work the conductor has already decomposed into independent units (args: {goal, units, testCommand})',
  phases: [
    { title: 'Execute', detail: 'one role agent per unit, isolated worktrees, one escalation on failure' },
    { title: 'Integrate', detail: 'integrator merges finished slices and runs the full suite' },
    { title: 'Verify', detail: 'fresh-context verifier tries to refute the combined result' },
  ],
}

// args = {
//   goal: string,                      // the overall outcome, with the why
//   testCommand: string,               // full-suite command for integrator + verifier
//   units: [{ id, title, role, spec, done }]
//     role: 'mech-executor' | 'executor' | 'senior-executor' | 'security-executor'
// }
// The conductor writes the plan inline (judgment) and passes it here; this script only executes it.

const LADDER = { 'mech-executor': 'executor', 'executor': 'senior-executor', 'senior-executor': null, 'security-executor': null }
const WRITERS = new Set(['mech-executor', 'executor', 'senior-executor', 'security-executor'])

const REPORT = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['done', 'blocked', 'failed'] },
    summary: { type: 'string' },
    branch: { type: 'string', description: 'git branch holding this unit\'s commits (commit your work before finishing)' },
    worktree_path: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
    verification: { type: 'string', description: 'what you ran and observed' },
    blocker: { type: 'string' },
  },
  required: ['status', 'summary', 'verification'],
}

const VERDICT = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['CONFIRMED', 'REFUTED', 'INCONCLUSIVE'] },
    evidence: { type: 'string' },
    failures: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdict', 'evidence'],
}

const goal = (args && args.goal) || ''
const units = (args && Array.isArray(args.units)) ? args.units : []
const testCommand = (args && args.testCommand) || '(discover the project\'s test command)'
if (!units.length) {
  return { error: 'execute-plan needs args.units — the conductor must decompose the task first' }
}

function unitPrompt(u, prior) {
  return [
    `Overall goal (context only): ${goal}`,
    `Your unit (${u.id}): ${u.title}`,
    `Spec:\n${u.spec}`,
    `Done-criteria:\n${u.done}`,
    'You are in an isolated git worktree. Work only inside it, never touch the main checkout.',
    'When done, commit your changes on the worktree branch and report the branch name and worktree path.',
    prior ? `A previous attempt on a lower tier failed. Its report:\n${prior}` : '',
  ].filter(Boolean).join('\n\n')
}

function runUnit(u, role, prior) {
  return agent(unitPrompt(u, prior), {
    label: `${u.id}:${role}`,
    phase: 'Execute',
    agentType: role,
    schema: REPORT,
    isolation: WRITERS.has(role) ? 'worktree' : undefined,
  })
}

phase('Execute')
const results = await pipeline(
  units,
  u => runUnit(u, u.role || 'executor', null),
  async (first, u) => {
    if (first && first.status === 'done') return { unit: u, role: u.role || 'executor', report: first }
    const next = LADDER[u.role || 'executor']
    if (!next) return { unit: u, role: u.role, report: first }
    log(`${u.id}: escalating ${u.role || 'executor'} → ${next}`)
    const second = await runUnit(u, next, first ? `${first.summary}\n${first.blocker || ''}` : 'agent died')
    return { unit: u, role: next, report: second }
  },
)

const done = results.filter(r => r && r.report && r.report.status === 'done')
const notDone = results.filter(r => !r || !r.report || r.report.status !== 'done')
if (notDone.length) log(`${notDone.length} unit(s) not done; they are excluded from integration`)
if (!done.length) {
  return { goal, integrated: false, units: results }
}

phase('Integrate')
const slices = done.map(r => `- ${r.unit.id} (${r.role}): branch ${r.report.branch || '?'} at ${r.report.worktree_path || '?'} — ${r.report.summary}`).join('\n')
const integration = await agent(
  [
    `Integrate these finished slices into the main checkout, in this order:\n${slices}`,
    `Full test command: ${testCommand}`,
    `Overall goal: ${goal}`,
  ].join('\n\n'),
  { label: 'integrator', phase: 'Integrate', agentType: 'integrator', schema: REPORT },
)

phase('Verify')
const verdict = await agent(
  [
    `Claim: the following goal is implemented in the main checkout and the full suite passes.\nGoal: ${goal}`,
    `Done-criteria per unit:\n${done.map(r => `- ${r.unit.id}: ${r.unit.done}`).join('\n')}`,
    `Integrator report: ${integration ? integration.summary + '\n' + integration.verification : 'integrator returned nothing'}`,
    `Test command: ${testCommand}`,
  ].join('\n\n'),
  { label: 'verifier', phase: 'Verify', agentType: 'verifier', schema: VERDICT },
)

return {
  goal,
  units: results.map(r => r && { id: r.unit.id, role: r.role, status: r.report && r.report.status, summary: r.report && r.report.summary, blocker: r.report && r.report.blocker }),
  integration,
  verdict,
}
