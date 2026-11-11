import { existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..', '..')
const candidates = process.platform === 'win32'
  ? [resolve(root, '.venv_tau', 'Scripts', 'python.exe'), resolve(root, '.venv312', 'Scripts', 'python.exe')]
  : [resolve(root, '.venv_tau', 'bin', 'python'), resolve(root, '.venv312', 'bin', 'python')]
const python = process.env.SERVICEFLOW_PYTHON ?? candidates.find(existsSync) ?? 'python'
const result = spawnSync(python, [resolve(root, 'scripts', 'run_phase4_e2e.py')], {
  cwd: root,
  env: process.env,
  stdio: 'inherit',
})

if (result.error) {
  console.error(`Unable to start the isolated E2E runner: ${result.error.message}`)
  process.exit(1)
}
process.exit(result.status ?? 1)
