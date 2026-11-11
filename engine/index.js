'use strict'
// JSON-RPC over stdio for the Python side.
//
// One JSON object per line. Requests come in as {id, method, params}, replies go out
// as {id, ok, result} or {id, ok:false, error}. Anything a source script prints is
// forwarded to stderr so it never corrupts the protocol stream.

const fs = require('fs')
const path = require('path')
const readline = require('readline')
const { createHost, parseScriptMeta } = require('./host/lx-shim')

const BUNDLED_DIR = path.join(__dirname, 'scripts')
// User-imported scripts live next to the executable, not inside the bundle.
const userArgIndex = process.argv.indexOf('--user-scripts')
const USER_DIR = userArgIndex > 0 ? process.argv[userArgIndex + 1] : null
const hosts = new Map()      // file -> { host, meta, sources, loadedAt }
const TIMEOUT_MS = 25000

function scriptDirs() {
  return [BUNDLED_DIR, USER_DIR].filter((dir) => dir && fs.existsSync(dir))
}

function scriptIndex() {
  const found = new Map()     // file name -> full path; user files win
  for (const dir of scriptDirs()) {
    for (const name of fs.readdirSync(dir)) {
      if (name.endsWith('.js')) found.set(name, path.join(dir, name))
    }
  }
  return found
}

function log(...args) {
  process.stderr.write(args.join(' ') + '\n')
}

function listScripts() {
  return [...scriptIndex().keys()]
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitInited(host, ms) {
  const started = Date.now()
  while (Date.now() - started < ms) {
    if (host.inited) return true
    await sleep(25)
  }
  return false
}

async function load(file) {
  if (hosts.has(file)) return hosts.get(file)
  const full = scriptIndex().get(file)
  if (!full) throw new Error('script not found: ' + file)
  const code = fs.readFileSync(full, 'utf8')
  const host = createHost(code, (line) => log('[script]', line))
  const ready = await waitInited(host, 8000)
  const entry = {
    host,
    meta: parseScriptMeta(code),
    sources: ready ? host.sources() : {},
    ready,
    loadedAt: new Date().toISOString(),
  }
  hosts.set(file, entry)
  return entry
}

function withTimeout(promise, ms, label) {
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timeout`)), ms)
  })
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer))
}

const methods = {
  ping() {
    return { pong: true, node: process.version }
  },

  async scripts() {
    const out = []
    for (const file of listScripts()) {
      try {
        const entry = await load(file)
        out.push({
          file,
          name: entry.meta.name,
          version: entry.meta.version,
          ready: entry.ready,
          sources: Object.fromEntries(
            Object.entries(entry.sources).map(([key, value]) => [
              key,
              { name: value.name, qualitys: value.qualitys, actions: value.actions },
            ]),
          ),
        })
      } catch (error) {
        out.push({ file, error: String(error.message || error) })
      }
    }
    return out
  },

  async resolve({ file, source, quality, musicInfo }) {
    const entry = await load(file)
    if (!entry.ready) throw new Error('script not initialised')
    const sourceInfo = entry.sources[source]
    if (!sourceInfo) throw new Error('source not supported: ' + source)
    const url = await withTimeout(
      entry.host.call({ source, action: 'musicUrl', info: { type: quality, musicInfo } }),
      TIMEOUT_MS,
      'resolve',
    )
    if (typeof url !== 'string' || !url.startsWith('http')) throw new Error('resolved non-http value')
    return { url }
  },
}

async function main() {
  const rl = readline.createInterface({ input: process.stdin, terminal: false })
  for await (const line of rl) {
    if (!line.trim()) continue
    let message
    try {
      message = JSON.parse(line)
    } catch {
      log('bad json request')
      continue
    }
    const { id, method, params } = message
    const handler = methods[method]
    if (!handler) {
      process.stdout.write(JSON.stringify({ id, ok: false, error: 'unknown method: ' + method }) + '\n')
      continue
    }
    try {
      const result = await handler(params || {})
      process.stdout.write(JSON.stringify({ id, ok: true, result }) + '\n')
    } catch (error) {
      process.stdout.write(JSON.stringify({ id, ok: false, error: String(error.message || error) }) + '\n')
    }
  }
}

main().catch((error) => {
  log('fatal:', error)
  process.exit(1)
})
