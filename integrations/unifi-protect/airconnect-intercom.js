// Copy beside protect-talkback.js. Uses that project's existing ws dependency.
import WebSocket from 'ws';
import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';

export function loadIntercomConfig() {
  const path = process.env.SONOS_NATIVE_CONFIG ?? new URL('./airconnect-intercom.local.json', import.meta.url);
  if (!existsSync(path)) return null;
  const config = JSON.parse(readFileSync(path, 'utf8'));
  if (!config.enabled) return null;
  if (!/^wss?:\/\//.test(config.url) || !config.tokenFile || !config.ffmpeg) throw new Error('Invalid native intercom configuration');
  return { ...config, token: readFileSync(config.tokenFile, 'utf8').trim() };
}

export class NativeIntercom {
  constructor(config, speaker, options = {}) {
    this.config = config;
    this.speaker = speaker;
    this.options = options;
    this.closed = false;
    this.ready = false;
    this.decoder = null;
    this.ws = null;
    this.pendingPCM = Buffer.alloc(0);
    this.decoderError = '';
  }

  open() {
    return new Promise((resolve, reject) => {
      this.rejectOpen = reject;
      this.ws = new WebSocket(this.config.url, { headers: { Authorization: `Bearer ${this.config.token}` },
        perMessageDeflate: false, handshakeTimeout: 5000, maxPayload: 65536 });
      this.timer = setTimeout(() => this.fail(new Error('Native Sonos preparation timed out')), 45000);
      this.timer.unref?.();
      this.heartbeat = setInterval(() => {
        if (this.ws.readyState === WebSocket.OPEN) this.ws.ping();
      }, 3000);
      this.heartbeat.unref?.();
      this.ws.on('open', () => this.ws.send(JSON.stringify({ type: 'start', room: this.speaker,
        format: 's16le', rate: 44100, channels: 2,
        volume: this.options.volume ?? this.config.volume ?? 35, muted: this.options.muted ?? false })));
      this.ws.on('message', (data, binary) => {
        if (binary || this.closed) return;
        let message;
        try { message = JSON.parse(data.toString()); } catch { return this.fail(new Error('Invalid native bridge response')); }
        if (message.type === 'error') return this.fail(new Error(message.message || 'Native bridge failed'));
        if (message.type === 'ready' && !this.ready) {
          this.ready = true;
          clearTimeout(this.timer);
          this.startDecoder();
          resolve(this);
        }
      });
      this.ws.on('error', error => this.fail(error));
      this.ws.on('close', () => { if (!this.closed) this.fail(new Error('Native Sonos session closed')); });
    });
  }

  startDecoder() {
    this.decoder = spawn(this.config.ffmpeg, ['-hide_banner', '-loglevel', 'error', '-nostdin',
      '-f', 'aac', '-probesize', '32', '-analyzeduration', '0', '-i', 'pipe:0',
      '-vn', '-ac', '2', '-ar', '44100', '-acodec', 'pcm_s16le', '-f', 's16le', '-flush_packets', '1', 'pipe:1'],
      { stdio: ['pipe', 'pipe', 'pipe'] });
    this.decoder.stdout.on('data', chunk => {
      if (this.closed) return;
      if (this.ws.bufferedAmount > 35280) return this.fail(new Error('Native audio connection is congested'));
      const data = this.pendingPCM.length ? Buffer.concat([this.pendingPCM, chunk]) : chunk;
      const length = data.length - data.length % 4;
      this.pendingPCM = Buffer.from(data.subarray(length));
      for (let offset = 0; offset < length; offset += 8192) {
        this.ws.send(data.subarray(offset, Math.min(offset + 8192, length)), { binary: true }, error => {
          if (error) this.fail(error);
        });
      }
    });
    this.decoder.stderr.on('data', data => { this.decoderError = (this.decoderError + data.toString()).slice(-1500); });
    this.decoder.stdin.on('error', error => { if (!this.closed) this.fail(error); });
    this.decoder.on('error', error => this.fail(error));
    this.decoder.on('exit', code => {
      if (!this.closed) this.fail(new Error(`AAC decoder exited (${code}): ${this.decoderError}`));
    });
  }

  writeAAC(data) {
    if (this.closed || !this.ready || !this.decoder) return;
    if (data.length > 256 * 1024 || this.decoder.stdin.writableLength > 32768) {
      return this.fail(new Error('Microphone audio input is congested'));
    }
    this.decoder.stdin.write(data);
  }

  fail(error) {
    if (this.closed) return;
    const wasReady = this.ready;
    this.close(error);
    this.rejectOpen?.(error);
    if (wasReady) this.options.onError?.(error);
  }

  close(error) {
    if (this.closed) return;
    this.closed = true;
    clearTimeout(this.timer); clearInterval(this.heartbeat);
    this.decoder?.stdin.destroy();
    this.decoder?.kill('SIGTERM');
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.close(1000, 'Intercom ended');
      const socket = this.ws;
      const timer = setTimeout(() => { if (socket.readyState !== WebSocket.CLOSED) socket.terminate(); }, 2000);
      timer.unref?.();
    } else this.ws?.terminate();
    if (!this.ready) this.rejectOpen?.(error || new Error('Intercom cancelled during setup'));
  }
}
