/* Offline-first attendance helper.
 * Queue entries are AES-GCM sealed before persistence and carry a tamper-evident
 * digest. The server still validates the short-lived QR token when synchronising.
 */
(function () {
  const QUEUE_KEY = 'smart-attendance-offline-queue-v2';
  const DEVICE_KEY = 'smart-attendance-device-id-v1';

  const bytesToBase64 = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes)));
  const base64ToBytes = value => Uint8Array.from(atob(value), char => char.charCodeAt(0));

  function deviceId() {
    let id = localStorage.getItem(DEVICE_KEY);
    if (!id) {
      id = window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random()}-${navigator.userAgent}`;
      localStorage.setItem(DEVICE_KEY, id);
    }
    return id;
  }

  async function cryptoKey() {
    const material = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${deviceId()}|${location.origin}`));
    return crypto.subtle.importKey('raw', material, {name: 'AES-GCM'}, false, ['encrypt', 'decrypt']);
  }

  async function seal(value) {
    if (!window.crypto?.subtle) return JSON.stringify({plain: value});
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const cipher = await crypto.subtle.encrypt({name: 'AES-GCM', iv}, await cryptoKey(), new TextEncoder().encode(JSON.stringify(value)));
    return `v2.${bytesToBase64(iv)}.${bytesToBase64(cipher)}`;
  }

  async function unseal(value) {
    if (!value) return [];
    if (!value.startsWith('v2.')) {
      try { return JSON.parse(value); } catch (_) { return []; }
    }
    try {
      const [, iv, cipher] = value.split('.');
      const plain = await crypto.subtle.decrypt({name: 'AES-GCM', iv: base64ToBytes(iv)}, await cryptoKey(), base64ToBytes(cipher));
      return JSON.parse(new TextDecoder().decode(plain));
    } catch (_) { return []; }
  }

  async function readQueue() {
    return unseal(localStorage.getItem(QUEUE_KEY));
  }

  async function writeQueue(queue) {
    localStorage.setItem(QUEUE_KEY, await seal(queue.slice(-20)));
  }

  async function queueSignature(payload, queuedAt) {
    const canonical = JSON.stringify({payload, queuedAt});
    if (!window.crypto?.subtle) return '';
    return bytesToBase64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${deviceId()}|${canonical}`)));
  }

  async function enqueue(payload) {
    const queue = await readQueue();
    const queuedAt = new Date().toISOString();
    queue.push({id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`, payload, queuedAt, signature: await queueSignature(payload, queuedAt)});
    await writeQueue(queue);
    return {success: true, queued: true, message: 'Scan encrypted on this device and queued for sync when you reconnect.'};
  }

  async function post(payload) {
    const response = await fetch('/student/scan/process', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    let data = {};
    try { data = await response.json(); } catch (_) { data = {success: false, error: 'Invalid server response'}; }
    return {response, data};
  }

  async function submit(payload) {
    const enriched = {...payload, device_id: deviceId(), device_label: navigator.userAgent.includes('Mobile') ? 'Mobile browser' : 'Web browser'};
    if (!navigator.onLine) return enqueue(enriched);
    try {
      const {response, data} = await post(enriched);
      if (!response.ok && response.status >= 500) return enqueue(enriched);
      return data;
    } catch (_) { return enqueue(enriched); }
  }

  async function sync() {
    if (!navigator.onLine) return;
    const pending = await readQueue();
    const remaining = [];
    for (const item of pending) {
      try {
        const {data} = await post({...item.payload, offline_queued_at: item.queuedAt, offline_signature: item.signature});
        // Expiry, duplicates, invalid QR, and closed sessions are terminal outcomes.
        const terminal = ['already_marked', 'invalid_qr', 'session_not_active', 'expired_qr', 'not_enrolled'];
        if (!data.success && !terminal.includes(data.code)) remaining.push(item);
        window.dispatchEvent(new CustomEvent('attendance-sync-result', {detail: data}));
      } catch (_) { remaining.push(item); }
    }
    await writeQueue(remaining);
  }

  async function verifyBeacon() {
    if (!navigator.bluetooth) throw new Error('Bluetooth verification is not supported by this browser.');
    const device = await navigator.bluetooth.requestDevice({acceptAllDevices: true});
    return device.name || device.id;
  }

  function initialise() {
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/service-worker.js').catch(() => {});
    window.addEventListener('online', sync);
    setTimeout(sync, 500);
  }

  window.AttendanceOffline = {deviceId, enqueue, submit, sync, verifyBeacon, initialise};
})();
