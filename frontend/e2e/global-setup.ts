import * as fs from 'fs'
import * as path from 'path'
import * as http from 'http'
import { spawn } from 'child_process'

const LOG_DIR = path.join(__dirname, 'logs')
const BACKEND_LOG = path.join(LOG_DIR, 'backend.log')
const BACKEND_PID = path.join(LOG_DIR, 'backend.pid')
const BACKEND_URL = 'http://localhost:8000/health'

function probeBackend(timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), timeoutMs)
    http.get(BACKEND_URL, (res) => {
      clearTimeout(timer)
      resolve(res.statusCode === 200)
    }).on('error', () => {
      clearTimeout(timer)
      resolve(false)
    })
  })
}

function waitForBackend(maxMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const poll = async () => {
      const up = await probeBackend(3_000)
      if (up) return resolve()
      if (Date.now() - start > maxMs) return reject(new Error('Backend did not start within timeout'))
      setTimeout(poll, 2_000)
    }
    poll()
  })
}

export default async function globalSetup() {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true })

  const alreadyRunning = await probeBackend(3_000)
  if (alreadyRunning) {
    console.log('[global-setup] Backend already running — reusing existing server')
    // Remove stale pid file so teardown won't kill a server we didn't start
    if (fs.existsSync(BACKEND_PID)) fs.unlinkSync(BACKEND_PID)
    return
  }

  console.log('[global-setup] Spawning backend: python main.py')
  const backendDir = path.resolve(__dirname, '../../backend')
  const logStream = fs.createWriteStream(BACKEND_LOG, { flags: 'a' })

  const proc = spawn('python', ['main.py'], {
    cwd: backendDir,
    detached: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  proc.stdout?.pipe(logStream)
  proc.stderr?.pipe(logStream)

  proc.on('error', (err) => {
    logStream.write(`[spawn error] ${err.message}\n`)
  })

  fs.writeFileSync(BACKEND_PID, String(proc.pid))
  console.log(`[global-setup] Backend PID ${proc.pid} — waiting for /health ...`)

  await waitForBackend(120_000)
  console.log('[global-setup] Backend is up.')
}
