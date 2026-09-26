import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const dir = mkdtempSync(join(tmpdir(), 'harness-cli-'))
const config = join(dir, 'config.json')
writeFileSync(config, '{}')
const args = ['--dry-run', '--db', join(dir, 'sessions.db'), '--config', config, '--logs', join(dir, 'logs')]
const env = { ...process.env, COMPUTER_USE_VLM_BASE_URL: '', NO_COLOR: '1' }
function run(extra, input) {
  return spawnSync('./build/harness-cli', [...args, ...extra], { input, encoding: 'utf8', env, timeout: 15000 })
}
try {
  let result = run(['-p', 'open Safari', '--json'])
  assert.equal(result.status, 0, result.stderr)
  let events = result.stdout.trim().split('\n').map(JSON.parse)
  const done = events.at(-1)
  assert.equal(done.status, 'success')
  assert.ok(events.some(e => e.type === 'step'))
  assert.ok(!events.some(e => e.type === 'computer_frame'))
  result = run([], `/history\n/show ${done.session_id}\n/target 42\n/new\n/help\n/quit\n`)
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /open Safari/)
  assert.match(result.stdout, /Target PID: 42/)
  assert.match(result.stdout, /New conversation/)
  assert.equal(run(['--target', '3x']).status, 1)
  assert.equal(run(['--json']).status, 1)
  assert.equal(run(['-p', '']).status, 1)
  assert.equal(run(['-p', 'do an unsupported complex task']).status, 1)
  result = run(['-p', 'open hello\x1b[2Jworld'])
  assert.ok(!result.stdout.includes('\x1b'), 'untrusted text must not emit terminal escapes')
  // Interrupt after the run begins, not before signal handlers are installed.
  const child = spawn('./build/harness-cli', [...args, '-p', 'wait 10000', '--json'], { env })
  let output = ''
  let sent = false
  const timeout = setTimeout(() => child.kill('SIGKILL'), 15000)
  child.stdout.on('data', chunk => {
    output += chunk
    if (!sent && output.includes('"type":"info"')) {
      sent = true
      child.kill('SIGINT')
    }
  })
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('exit', resolve) })
  clearTimeout(timeout)
  assert.equal(code, 130, output)
  assert.match(output, /"status":"cancelled"/)
  console.log('CLI commands, persistence, JSON streaming, validation, terminal escaping and SIGINT checks passed')
} finally {
  rmSync(dir, { recursive: true, force: true })
}
