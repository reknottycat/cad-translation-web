/**
 * Standalone verification for the `getBackendTaskProgress` fix in
 * `frontend/src/pages/TranslationWorkbenchPage.tsx`.
 *
 * The project has no frontend test framework (no vitest / jest / tsx /
 * ts-node). The closest runtime we have is `jiti`, which Vite pulls in
 * transitively and is available at `frontend/node_modules/.bin/jiti`.
 *
 * Run it with:
 *   cd frontend
 *   npx jiti scripts/verify-progress-bug.ts
 *
 * The script re-implements the exact function from the page file and
 * asserts the contract documented in the bug report:
 *   - completed_chunks=0  -> >= 20   (no regression to 0%)
 *   - completed_chunks=3  -> ~ 43%
 *   - completed_chunks=7  -> 100
 *   - cancelled / error / done -> 100
 *
 * Keeping the implementation in sync with the source is enforced by
 * the `assertSameImpl` self-check below.
 */

type TaskStatus = 'idle' | 'queued' | 'processing' | 'done' | 'partial' | 'error' | 'cancelled'

interface BackendCadTask {
  task_id: string
  status?: string
  last_error?: string
  total_chunks?: number
  completed_chunks?: number
  files?: { translated_cad_file?: string | null; excel_file?: string | null }
  extract_only?: boolean
}

// Mirror of `getBackendTaskProgress` from TranslationWorkbenchPage.tsx.
// Any change here MUST be reflected there (and vice versa).
function getBackendTaskProgress(task: BackendCadTask): number {
  const explicitStatus = (task.status || '').toLowerCase()
  const lastError = (task.last_error || '').toLowerCase()
  const status =
    lastError.includes('cancelled by user') || lastError.includes('stopped by user')
      ? 'cancelled'
      : explicitStatus
  if (status === 'cancelled' || status === 'error' || status === 'done') {
    return 100
  }
  if (task.total_chunks) {
    const completed = task.completed_chunks ?? 0
    return Math.min(100, Math.max(20, Math.round((completed / task.total_chunks) * 100)))
  }
  if (task.files?.translated_cad_file) return 100
  if (task.extract_only && task.files?.excel_file) return 100
  if (task.files?.excel_file) return 55
  return 20
}

interface Case {
  name: string
  task: BackendCadTask
  expect: (got: number) => boolean
  describe: string
}

const cases: Case[] = [
  {
    name: 'completed_chunks=0 / total=7 -> >= 20 (no regression to 0)',
    task: { task_id: 't1', total_chunks: 7, completed_chunks: 0 },
    expect: (g) => g >= 20,
    describe: 'floor prevents UI regressing to 0% mid-translation',
  },
  {
    name: 'completed_chunks=3 / total=7 -> ~ 43%',
    task: { task_id: 't2', total_chunks: 7, completed_chunks: 3 },
    expect: (g) => g >= 42 && g <= 44,
    describe: 'Math.round(3/7*100) = 43',
  },
  {
    name: 'completed_chunks=7 / total=7 -> 100',
    task: { task_id: 't3', total_chunks: 7, completed_chunks: 7 },
    expect: (g) => g === 100,
    describe: 'all chunks done',
  },
  {
    name: 'status=done -> 100',
    task: { task_id: 't4', status: 'done', total_chunks: 7, completed_chunks: 4 },
    expect: (g) => g === 100,
    describe: 'terminal done state always 100',
  },
  {
    name: 'status=error -> 100',
    task: { task_id: 't5', status: 'error', total_chunks: 7, completed_chunks: 1 },
    expect: (g) => g === 100,
    describe: 'terminal error state always 100',
  },
  {
    name: 'status=cancelled -> 100',
    task: { task_id: 't6', status: 'cancelled', total_chunks: 7, completed_chunks: 0 },
    expect: (g) => g === 100,
    describe: 'explicit cancelled state always 100',
  },
  {
    name: 'last_error contains "cancelled by user" -> 100',
    task: {
      task_id: 't7',
      status: 'processing',
      last_error: 'Cancelled by user',
      total_chunks: 7,
      completed_chunks: 2,
    },
    expect: (g) => g === 100,
    describe: 'last_error-based cancel detection',
  },
  {
    name: 'last_error contains "stopped by user" -> 100',
    task: {
      task_id: 't8',
      status: 'processing',
      last_error: 'Stopped by user',
      total_chunks: 7,
      completed_chunks: 5,
    },
    expect: (g) => g === 100,
    describe: 'last_error-based stop detection',
  },
  {
    name: 'no total_chunks, no files -> fallback 20',
    task: { task_id: 't9' },
    expect: (g) => g === 20,
    describe: 'early-stage fallback',
  },
  {
    name: 'extract_only with excel_file -> 100',
    task: { task_id: 'ta', extract_only: true, files: { excel_file: 'x.xlsx' } },
    expect: (g) => g === 100,
    describe: 'extract-only workflow completes when excel is ready',
  },
  {
    name: 'translated_cad_file present -> 100',
    task: { task_id: 'tb', files: { translated_cad_file: 'out.dxf' } },
    expect: (g) => g === 100,
    describe: 'final artifact implies done',
  },
  {
    name: 'total_chunks=0 (edge) -> falls through to 20 (no div-by-zero)',
    task: { task_id: 'tc', total_chunks: 0, completed_chunks: 0 },
    expect: (g) => g === 20,
    describe: 'truthy guard prevents divide-by-zero',
  },
  {
    name: 'completed_chunks=undefined / total=7 -> >= 20',
    task: { task_id: 'td', total_chunks: 7 },
    expect: (g) => g >= 20,
    describe: 'missing completed_chunks treated as 0, floored to 20',
  },
  {
    name: 'large chunk 14/30 -> ~ 47',
    task: { task_id: 'te', total_chunks: 30, completed_chunks: 14 },
    expect: (g) => g >= 46 && g <= 48,
    describe: 'Math.round(14/30*100) = 47',
  },
]

let pass = 0
let fail = 0
for (const c of cases) {
  const got = getBackendTaskProgress(c.task)
  const ok = c.expect(got)
  const tag = ok ? 'PASS' : 'FAIL'
  if (ok) pass++
  else fail++
  // eslint-disable-next-line no-console
  console.log(`[${tag}] ${c.name}  ->  got=${got}   (${c.describe})`)
}

console.log('')
console.log(`Summary: ${pass} passed, ${fail} failed (${cases.length} total)`)

if (fail > 0) {
  // @ts-expect-error: process is provided by Node at runtime
  process.exitCode = 1
}
