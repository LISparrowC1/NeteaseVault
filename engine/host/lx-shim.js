'use strict'
// Minimal LX custom-source host.
//
// The LX app hands each source script a `globalThis.lx` object; this file provides
// the same contract outside Electron. See docs/方案.md 4.2.

const crypto = require('crypto')
const zlib = require('zlib')
const vm = require('vm')
const { promisify } = require('util')

const inflate = promisify(zlib.inflate)
const deflate = promisify(zlib.deflate)

const EVENT_NAMES = Object.freeze({ inited: 'inited', request: 'request', updateAlert: 'updateAlert' })

function parseScriptMeta(code) {
  const pick = (key) => {
    const match = code.match(new RegExp(`@${key}\\s+(.+)`))
    return match ? match[1].trim() : ''
  }
  return {
    name: pick('name'),
    description: pick('description'),
    version: pick('version'),
    author: pick('author'),
    homepage: pick('homepage'),
  }
}

function createHost(code, log = () => {}) {
  const handlers = new Map()
  let inited = null
  let updateAlert = null

  const request = (url, options = {}, callback) => {
    const controller = new AbortController()
    const finish = (err, resp) => {
      try {
        callback(err, resp)
      } catch (error) {
        log(`callback threw: ${error.message}`)
      }
    }
    ;(async () => {
      const method = options.method || 'GET'
      const headers = Object.assign({}, options.headers)
      let payload
      if (options.form) {
        payload = new URLSearchParams(options.form).toString()
        headers['Content-Type'] = headers['Content-Type'] || 'application/x-www-form-urlencoded'
      } else if (options.formData) {
        payload = new URLSearchParams(options.formData).toString()
        headers['Content-Type'] = headers['Content-Type'] || 'application/x-www-form-urlencoded'
      } else if (options.body !== undefined) {
        payload = typeof options.body === 'string' ? options.body : JSON.stringify(options.body)
        headers['Content-Type'] = headers['Content-Type'] || 'application/json'
      }
      const timer = setTimeout(() => controller.abort(), options.timeout || 15000)
      try {
        const res = await fetch(url, { method, headers, body: payload, signal: controller.signal })
        const text = await res.text()
        let body = text
        if ((res.headers.get('content-type') || '').includes('json') || /^\s*[[{]/.test(text)) {
          try {
            body = JSON.parse(text)
          } catch {
            body = text
          }
        }
        log(`RES ${res.status} ${url.slice(0, 120)}`)
        finish(null, { statusCode: res.status, headers: Object.fromEntries(res.headers.entries()), body })
      } catch (error) {
        log(`ERR ${method} ${url.slice(0, 120)} -> ${error.name}: ${error.message}`)
        finish(error, null)
      } finally {
        clearTimeout(timer)
      }
    })()
    return () => controller.abort()
  }

  const utils = {
    buffer: {
      from: (...args) => Buffer.from(...args),
      bufToString: (buffer, format) => (Buffer.isBuffer(buffer) ? buffer.toString(format || 'utf8') : String(buffer)),
    },
    crypto: {
      aesEncrypt: (buffer, mode, key, iv) => {
        const cipher = crypto.createCipheriv(mode, key, iv)
        return Buffer.concat([cipher.update(buffer), cipher.final()])
      },
      md5: (text) => crypto.createHash('md5').update(text).digest('hex'),
      randomBytes: (size) => crypto.randomBytes(size).toString('hex'),
      rsaEncrypt: (buffer, key) => crypto.publicEncrypt({ key, padding: crypto.constants.RSA_PKCS1_PADDING }, buffer),
    },
    zlib: { inflate, deflate },
  }

  const lx = {
    version: 2,
    env: 'desktop',
    currentScriptInfo: Object.assign(parseScriptMeta(code), { rawScript: code }),
    EVENT_NAMES,
    on: (name, handler) => handlers.set(name, handler),
    send: (name, data) => {
      if (name === EVENT_NAMES.inited) inited = data
      else if (name === EVENT_NAMES.updateAlert) updateAlert = data
    },
    request,
    utils,
  }

  const quiet = () => {}
  const consoleShim = {
    log: (...args) => log('script ' + args.map(format).join(' ')),
    error: (...args) => log('script.err ' + args.map(format).join(' ')),
    warn: quiet,
    info: quiet,
    debug: quiet,
    group: quiet,
    groupEnd: quiet,
  }

  const context = vm.createContext({
    lx,
    globalThis: null,
    console: consoleShim,
    Buffer,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    TextEncoder,
    TextDecoder,
    URL,
    URLSearchParams,
  })
  context.globalThis = context
  vm.runInContext(code, context, { filename: 'source.js', timeout: 10000 })

  return {
    get inited() {
      return inited
    },
    get updateAlert() {
      return updateAlert
    },
    sources: () => (inited && inited.sources) || {},
    call(payload) {
      const handler = handlers.get(EVENT_NAMES.request)
      if (!handler) return Promise.reject(new Error('script registered no request handler'))
      return handler(payload)
    },
  }
}

function format(value) {
  if (typeof value === 'object' && value !== null) {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

module.exports = { createHost, parseScriptMeta, EVENT_NAMES }
