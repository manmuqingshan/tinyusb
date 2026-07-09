export const meta = {
  name: 'validate',
  description: 'Pre-PR software validation: unit tests + per-board build sweeps + code-size compare + PVS, in parallel, joined into one verdict',
  whenToUse: 'Before opening or updating a PR, after any non-trivial change',
  phases: [{ title: 'Validate', detail: 'unit + builds + size + pvs in parallel' }],
}

// args: { boards: string[], examples?: string, base?: string, skip?: ('unit'|'size'|'pvs')[] }
if (typeof args === 'string') args = JSON.parse(args)  // tolerate stringified invocation args
if (!args || !Array.isArray(args.boards) || args.boards.length === 0) {
  throw new Error('args must be { boards: string[], examples?, base?, skip? }')
}
const skip = args.skip || []
for (const s of skip) log(`stage skipped by request: ${s}`)
const base = args.base || 'master'
const clip = (s, n = 800) =>
  s.length > n ? s.slice(0, n) + ` …[truncated ${s.length - n} chars]` : s

const STAGE = {
  type: 'object', additionalProperties: false,
  required: ['pass', 'detail'],
  properties: { pass: { type: 'boolean' }, detail: { type: 'string' } },
}
const BUILD = {
  type: 'object', additionalProperties: false,
  required: ['board', 'pass', 'builtCount', 'failures'],
  properties: {
    board: { type: 'string' }, pass: { type: 'boolean' }, builtCount: { type: 'integer' },
    failures: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['example', 'class', 'firstError'],
        properties: { example: { type: 'string' }, class: { type: 'string' }, firstError: { type: 'string' } },
      },
    },
  },
}

const thunks = []

if (!skip.includes('unit')) thunks.push(() =>
  agent(
    'Run the TinyUSB unit tests: cd test/unit-test && ceedling test:all. ' +
    'pass=true only if every test passes. detail = the ceedling summary line, or the first failing test output.',
    { label: 'unit', phase: 'Validate', model: 'haiku', schema: STAGE },
  ).then(r => r && { stage: 'unit', ...r }))

for (const b of args.boards) thunks.push(() =>
  agent(
    `Build TinyUSB examples for board ${b}` + (args.examples ? ` (only: ${args.examples})` : ' (full example set)') + '.',
    { label: `build:${b}`, phase: 'Validate', agentType: 'builder', schema: BUILD },
  ).then(r => r && {
    stage: `build:${b}`, pass: r.pass,
    detail: r.pass ? `${r.builtCount} examples built` : clip(JSON.stringify(r.failures)),
  }))

if (!skip.includes('size')) thunks.push(() =>
  agent(
    `Compare TinyUSB code size against ${base}: python3 tools/metrics_compare_base.py -b ${args.boards[0]} -e device/cdc_msc . ` +
    'The report lands in cmake-metrics/<board>/metrics_compare.md. pass=false only if the tool itself errors; ' +
    'detail = the flash/RAM delta summary from the report (mention any example that grew).',
    { label: 'size', phase: 'Validate', model: 'haiku', schema: STAGE },
  ).then(r => r && { stage: 'size', ...r }))

if (!skip.includes('pvs')) thunks.push(() =>
  agent(
    'Run PVS-Studio static analysis per .claude/skills/pvs/SKILL.md, but with a DEDICATED build dir so you do not collide with parallel build agents: ' +
    `cd examples && cmake -B cmake-build-pvs -DBOARD=${args.boards[0]} -G Ninja -DCMAKE_BUILD_TYPE=MinSizeRel . && cmake --build cmake-build-pvs. ` +
    'Then: pvs-studio-analyzer analyze -f examples/cmake-build-pvs/compile_commands.json -R .PVS-Studio/.pvsconfig -o pvs-report.log -j12 ' +
    '--security-related-issues --misra-c-version 2023 --misra-cpp-version 2008 --use-old-parser ' +
    'and view with: plog-converter -a GA:1,2 -t errorfile pvs-report.log. ' +
    `pass=false only if GA:1 diagnostics exist in files changed vs ${base} (git diff --name-only ${base}...HEAD). ` +
    'detail = GA:1/GA:2 counts plus any diagnostics in changed files.',
    { label: 'pvs', phase: 'Validate', model: 'sonnet', effort: 'low', schema: STAGE },
  ).then(r => r && { stage: 'pvs', ...r }))

const results = (await parallel(thunks)).filter(Boolean)
const dead = thunks.length - results.length
if (dead > 0) log(`${dead} stage agent(s) died — counted as failures`)
const failures = results.filter(r => !r.pass)
log(`${results.length}/${thunks.length} stages completed, ${failures.length} failing`)
return { pass: failures.length === 0 && dead === 0, stages: results, failures }
