import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import WebSocket, { WebSocketServer } from 'ws';
import { ProtectTalkbackService } from './protect-talkback.js';

test('Protect waits for native readiness, retains camera forwarding and closes cleanly', async () => {
  const bridge = new WebSocketServer({host:'127.0.0.1', port:0});
  const camera = new WebSocketServer({host:'127.0.0.1', port:0});
  await Promise.all([bridge,camera].map(s => new Promise(r => s.once('listening',r))));
  const delay = ms => new Promise(r => setTimeout(r,ms));
  async function until(fn) { const end=Date.now()+4000; while(!fn()){if(Date.now()>end)throw new Error('Timed out');await delay(20);} }
  let peer, cameraBytes=0, start;
  camera.on('connection',ws=>ws.on('message',data=>cameraBytes+=data.length));
  bridge.on('connection',ws=>{peer=ws;ws.on('message',(data,binary)=>{if(!binary)start=JSON.parse(data.toString());});});
  const client = new EventEmitter(); client.readyState=WebSocket.OPEN; const messages=[];
  client.send=data=>messages.push(JSON.parse(data));
  client.close=()=>{client.readyState=WebSocket.CLOSED;client.emit('close');};
  const api={bootstrap:{cameras:[{id:'camera'}]},headers:{},getWsEndpoint:async()=>`ws://127.0.0.1:${camera.address().port}`};
  const service=new ProtectTalkbackService(api,{nativeConfig:{enabled:true,url:`ws://127.0.0.1:${bridge.address().port}`,token:'fixture',ffmpeg:process.env.FFMPEG_PATH||'/usr/local/bin/ffmpeg'}});
  try {
    const pending=service.bridge(client,'camera',{sonosSpeaker:'Test room'});
    await until(()=>start); await delay(100);
    assert.equal(messages.some(m=>m.type==='ready'),false);
    peer.send(JSON.stringify({type:'ready'})); await pending;
    assert.equal(messages[0].transport,'native-udp');
    assert.equal(service.sessions.size,0); // No HTTP radio session or resume polling.
    client.emit('message',Buffer.from([1,2,3,4]),true);
    await until(()=>cameraBytes===4);
    client.close(); await until(()=>peer.readyState===WebSocket.CLOSED);
  } finally {
    client.close();
    for(const server of [bridge,camera]){for(const ws of server.clients)ws.terminate();await new Promise(r=>server.close(r));}
  }
});
