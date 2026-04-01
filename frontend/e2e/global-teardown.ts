import * as fs from 'fs'
import * as path from 'path'

const BACKEND_PID = path.join(__dirname, 'logs', 'backend.pid')

export default async function globalTeardown() {
  if (!fs.existsSync(BACKEND_PID)) {
    console.log('[global-teardown] No PID file — backend was pre-existing, skipping kill.')
    return
  }

  const pid = parseInt(fs.readFileSync(BACKEND_PID, 'utf8').trim(), 10)
  if (isNaN(pid)) {
    console.log('[global-teardown] Invalid PID in file, skipping kill.')
    fs.unlinkSync(BACKEND_PID)
    return
  }

  try {
    process.kill(pid)
    console.log(`[global-teardown] Killed backend PID ${pid}`)
  } catch (err: any) {
    console.log(`[global-teardown] Could not kill PID ${pid}: ${err.message}`)
  } finally {
    fs.unlinkSync(BACKEND_PID)
  }
}
