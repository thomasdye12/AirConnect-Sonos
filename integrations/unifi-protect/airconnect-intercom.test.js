import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { WebSocketServer } from 'ws';
import { NativeIntercom } from './airconnect-intercom.js';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, ms = 6000) {
  const end = Date.now() + ms;
  while (!predicate()) { if (Date.now() > end) throw new Error('Timed out'); await delay(20); }
}

test('waits for bridge readiness, decodes AAC to PCM and cleans up', async () => {
  const ffmpeg = process.env.FFMPEG_PATH || '/usr/local/bin/ffmpeg';
  const audio = execFileSync(ffmpeg, ['-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=300:duration=3', '-c:a', 'aac', '-f', 'adts', 'pipe:1']);
  const server = new WebSocketServer({ host: '127.0.0.1', port: 0 });
  await new Promise(resolve => server.once('listening', resolve));
  let peer, start, bytes = 0, auth, streamError;
  server.on('connection', (ws, request) => {
    peer = ws; auth = request.headers.authorization;
    ws.on('message', (data, binary) => {
      if (binary) { assert.equal(data.length % 4, 0); bytes += data.length; }
      else { start = JSON.parse(data.toString()); ws.send(JSON.stringify({ type: 'preparing' })); }
    });
  });
  const session = new NativeIntercom({ url: `ws://127.0.0.1:${server.address().port}`, token: 'fixture', ffmpeg }, 'Test room', { onError: e => { streamError = e; } });
  try {
    let ready = false;
    const opened = session.open().then(() => { ready = true; });
    await until(() => start);
    assert.equal(auth, 'Bearer fixture'); assert.equal(start.rate, 44100); assert.equal(start.volume, 35);
    await delay(100); assert.equal(ready, false); assert.equal(session.decoder, null);
    peer.send(JSON.stringify({ type: 'ready' })); await opened;
    // Live AAC must produce output without waiting for end-of-input.
    for (let offset = 0; offset < audio.length; offset += 1024) {
      session.writeAAC(audio.subarray(offset, offset + 1024)); await delay(20);
    }
    await until(() => bytes > 10000);
    assert.equal(streamError, undefined);
    const decoder = session.decoder;
    session.close(); await until(() => decoder.exitCode !== null || decoder.signalCode !== null);
    assert.equal(session.closed, true);
  } finally {
    session.close(); for (const client of server.clients) client.terminate();
    await new Promise(resolve => server.close(resolve));
  }
});

test('bridge refusal rejects setup and never starts a decoder', async () => {
  const server = new WebSocketServer({ host: '127.0.0.1', port: 0 });
  await new Promise(resolve => server.once('listening', resolve));
  server.on('connection', ws => ws.on('message', () => ws.send(JSON.stringify({ type: 'error', message: 'Room busy' }))));
  const session = new NativeIntercom({ url: `ws://127.0.0.1:${server.address().port}`, token: 'fixture', ffmpeg: '/not-used' }, 'Test room');
  try {
    await assert.rejects(session.open(), /Room busy/);
    assert.equal(session.decoder, null); assert.equal(session.closed, true);
  } finally {
    session.close(); for (const client of server.clients) client.terminate();
    await new Promise(resolve => server.close(resolve));
  }
});
