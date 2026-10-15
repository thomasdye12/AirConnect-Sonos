'use strict';
let snapshot = null;
const $ = id => document.getElementById(id);
const set = (id, value) => { $(id).textContent = value; };
const num = value => value === null || value === undefined ? '—' : Number(value).toLocaleString();
const time = value => value ? new Date(value * 1000).toLocaleTimeString() : 'unknown';
const node = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; };
const badge = (text, cls) => node('span', text, 'badge ' + (cls || ''));
function uptime(seconds) { if (seconds === null || seconds === undefined) return ''; return seconds < 3600 ? Math.floor(seconds / 60) + 'm uptime' : Math.floor(seconds / 3600) + 'h ' + Math.floor(seconds % 3600 / 60) + 'm uptime'; }
function renderRooms() {
  if (!snapshot || !snapshot.ready) return;
  const query = $('search').value.toLowerCase(), filter = $('filter').value;
  const list = snapshot.rooms.filter(r => {
    const mode = r.is_helper ? 'helper' : r.coordinator !== r.uuid ? 'grouped' : r.settings.native_udp === '1' ? 'native' : 'http';
    return (r.name + ' ' + r.uuid + ' ' + (r.address || '')).toLowerCase().includes(query) && (filter === 'all' || (filter === 'active' ? r.session_held && !r.is_helper : mode === filter));
  });
  $('rooms').replaceChildren();
  list.forEach(r => {
    const tr = node('tr'), name = node('td');
    name.append(node('div', r.name, 'room-name'), node('small', r.is_helper ? 'Reserved for session setup' : r.coordinator !== r.uuid ? 'Grouped under ' + r.group_name : r.airplay_name));
    if (r.address) name.append(node('small', r.address));
    const mode = node('td');
    const grouped = r.coordinator !== r.uuid;
    mode.append(badge(r.is_helper ? 'Helper' : grouped ? 'Via group coordinator' : r.settings.native_udp === '1' ? 'Native UDP' : 'HTTP stream', r.is_helper ? 'helper' : grouped ? '' : r.settings.native_udp === '1' ? 'native' : 'http'));
    if (r.settings.native_muted === '1' && !r.is_helper && !grouped && r.settings.native_udp === '1') mode.append(node('small', 'Configured muted'));
    const ownership = node('td');
    ownership.append(badge(r.session_held === null ? 'Unknown' : r.session_held ? 'Session held' : 'No session held', r.session_held ? 'held' : ''));
    if (r.phase && !r.is_helper) ownership.append(node('small', r.phase));
    const state = node('td', String(r.sonos_state).replaceAll('_', ' ').toLowerCase());
    if (snapshot.api.stale) state.append(node('small', 'Stale API snapshot'));
    if (r.track.title) { const title = node('small', r.track.title.length > 42 ? r.track.title.slice(0, 42) + '…' : r.track.title); title.title = [r.track.title, r.track.artist].filter(Boolean).join(' · '); state.append(title); }
    const volume = node('td', r.volume === null || r.volume === undefined ? '—' : r.volume + (r.muted ? ' · muted' : ''));
    const offset = node('td', r.is_helper || grouped || r.settings.native_udp !== '1' ? '—' : (Number(r.settings.native_sync_offset_ms) > 0 ? '+' : '') + r.settings.native_sync_offset_ms + ' ms');
    tr.append(name, mode, ownership, state, volume, offset); $('rooms').append(tr);
  });
  if (!list.length) { const tr = node('tr'), td = node('td', 'No matching rooms.'); td.colSpan = 6; tr.append(td); $('rooms').append(tr); }
}
function records(id, items, title, fields) {
  const root = $(id); root.replaceChildren();
  if (!items.length) { root.append(node('p', 'No completed-session records in the available log.', 'empty')); return; }
  items.forEach(item => {
    const row = node('div', undefined, 'record'), heading = node('div', undefined, 'record-title');
    heading.append(node('span', title(item)), node('time', item.log_time + ' · log time'));
    const stats = node('div', undefined, 'stats');
    fields.forEach(([key, label]) => { const stat = node('span'); stat.append(node('b', num(item[key])), document.createTextNode(label)); stats.append(stat); });
    row.append(heading, stats); root.append(row);
  });
}
function renderEvents() {
  if (!snapshot || !snapshot.ready) return;
  const root = $('events'), warnings = $('warnings').checked;
  root.replaceChildren();
  const events = snapshot.logs.events.filter(e => !warnings || e.level === 'warning');
  events.forEach(e => root.append(node('div', e.text, 'event ' + e.level)));
  if (!events.length) root.append(node('p', warnings ? 'No warnings in the available recent events.' : 'No recent events available.', 'empty'));
}
function render(data) {
  snapshot = data;
  const age = Date.now() / 1000 - data.collected_at;
  if (!data.ready) { $('notice').hidden = false; set('notice', data.collector_error || 'Reading bridge status…'); return; }
  const notices = [...data.errors];
  if (data.collector_error) notices.push('Collection failed; showing the previous snapshot. ' + data.collector_error);
  if (age > 25) notices.push('Status is stale. Last collection: ' + time(data.collected_at));
  if (data.api.stale) notices.push('Room API unavailable. Room state is cached from ' + time(data.api.fetched_at) + '. ' + data.api.error);
  if (!data.service.running) notices.push('Bridge service: ' + data.service.ActiveState + (data.service.error ? ' · ' + data.service.error : ''));
  if (data.unknown_sessions.length) notices.push('Held sessions missing from the room list: ' + data.unknown_sessions.join(', '));
  $('notice').hidden = !notices.length; set('notice', notices.join(' '));
  set('freshness', 'Updated ' + time(data.collected_at));
  set('service', data.service.running ? 'Running' : data.service.ActiveState);
  set('version', (data.logs.version || 'Version unavailable') + ' · ' + uptime(data.service.uptime_seconds));
  $('version').title = 'Version from latest available startup log. Service start: ' + (data.service.ExecMainStartTimestamp || 'unknown');
  set('sessions', num(data.native_sessions)); set('roomCount', data.rooms.length);
  set('roomSource', (data.api.stale ? 'Cached' : 'Live API') + ' · fetched ' + time(data.api.fetched_at));
  set('helper', data.helper.name || 'Not configured');
  set('helperState', (data.helper.address || '') + ' · ' + (data.helper.held === null ? 'Ownership unknown' : data.helper.held ? 'In use by bridge' : 'Not held by bridge'));
  set('logInfo', 'Latest events first · device log time · ' + (data.logs.has_start_marker ? 'since last available startup' : 'partial log window') + (data.logs.modified_at ? ' · last write ' + time(data.logs.modified_at) : ''));
  set('host', data.host.hostname + ' · load ' + data.host.load[0].toFixed(2) + ' · refresh 5s / rooms 15s');
  const intercom = data.intercom || {available: false, sessions: [], recent: []};
  set('intercomState', !intercom.available ? 'Input service not available' : intercom.stale ? 'Input status is stale' : 'Input online · ' + intercom.sessions.length + ' session(s) · source: PCM intercom');
  records('intercomSessions', [...intercom.sessions, ...intercom.recent.slice(-3).reverse()].map(i => ({...i, log_time: time(i.ended_at || i.started_at)})), i => i.room + ' · ' + i.state + (i.muted ? ' · muted' : '') + (i.error ? ' · ' + i.error : ''), [['received_bytes', 'PCM bytes'], ['dropped_frames', 'dropped frames'], ['queued_frames', 'queued frames']]);
  renderRooms(); renderEvents();
  records('completed', data.logs.completed, i => i.room, [['packets','packets'],['late','late'],['clocks','clock requests'],['signal_frames','signal frames']]);
  records('timing', data.logs.timing, () => 'Native PCM output', [['samples','samples'],['dropped_frames','dropped frames'],['realignments','realignments'],['wait_blocks','wait blocks']]);
}
async function refresh() {
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch('/api/status', {cache:'no-store', signal:controller.signal});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    render(await response.json());
  } catch (error) {
    $('notice').hidden = false;
    set('notice', 'Dashboard connection lost. ' + (snapshot ? 'Showing the last snapshot from ' + time(snapshot.collected_at) + '. ' : '') + 'Retrying automatically.');
    set('freshness', 'Disconnected');
  } finally { clearTimeout(timeout); setTimeout(refresh, 5000); }
}
$('search').addEventListener('input', renderRooms); $('filter').addEventListener('change', renderRooms); $('warnings').addEventListener('change', renderEvents);
refresh();
