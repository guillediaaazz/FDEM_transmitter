const NUS_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
const NUS_RX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'; // Browser -> transmitter
const NUS_TX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'; // Transmitter -> browser
const BAUD_RATE = 115200;
const SETTINGS_DEBOUNCE_MS = 180;
const TRIM_DEBOUNCE_MS = 80;
const DAC_B_LSB_VOLTS = 2.048 / 4096;
const POWER_STAGE_GAIN = 16.667;

const $ = (id) => document.getElementById(id);
const elements = {
  connectionBadge: $('connectionBadge'), connectionDetail: $('connectionDetail'), connectionHint: $('connectionHint'),
  offlineStatus: $('offlineStatus'), browserStatus: $('browserStatus'), installBtn: $('installBtn'), updateBtn: $('updateBtn'),
  connectBleBtn: $('connectBleBtn'), connectUsbBtn: $('connectUsbBtn'), disconnectBtn: $('disconnectBtn'),
  controlFieldset: $('controlFieldset'), frequencyNumber: $('frequencyNumber'), frequencyRange: $('frequencyRange'),
  amplitudeNumber: $('amplitudeNumber'), amplitudeRange: $('amplitudeRange'), offsetTrimRange: $('offsetTrimRange'), offsetTrimValue: $('offsetTrimValue'),
  trimDecreaseBtn: $('trimDecreaseBtn'), trimIncreaseBtn: $('trimIncreaseBtn'),
  bluetoothSwitch: $('bluetoothSwitch'), statusBtn: $('statusBtn'), helpBtn: $('helpBtn'),
  outputIndicator: $('outputIndicator'), positiveRail: $('positiveRail'), negativeRail: $('negativeRail'), batteryPercent: $('batteryPercent'),
  batteryMeter: $('batteryMeter'), telemetryAge: $('telemetryAge'), statusWaveform: $('statusWaveform'),
  statusManualTrim: $('statusManualTrim'), statusBluetooth: $('statusBluetooth'),
  logOutput: $('logOutput'), clearLogBtn: $('clearLogBtn')
};

const state = {
  transport: null,
  connected: false,
  ble: { device: null, txCharacteristic: null, rxCharacteristic: null },
  serial: { port: null, writer: null, reader: null, readTask: null },
  receiveBuffer: '',
  writeQueue: Promise.resolve(),
  waveform: 'S',
  settingsTimer: null,
  trimTimer: null,
  deviceStateKnown: false,
  lastTelemetryAt: 0,
  updateRequested: false,
  deferredInstallPrompt: null
};

function log(direction, message) {
  const timestamp = new Date().toLocaleTimeString([], { hour12: false });
  const line = `[${timestamp}] ${direction} ${message}`;
  const current = elements.logOutput.textContent.split('\n').filter(Boolean);
  current.push(line);
  elements.logOutput.textContent = current.slice(-160).join('\n');
  elements.logOutput.scrollTop = elements.logOutput.scrollHeight;
}

function setNotice(element, text, level = 'idle') {
  element.textContent = text;
  element.classList.toggle('is-ready', level === 'ready');
  element.classList.toggle('is-warning', level === 'warning');
}

function setConnectionStatus(status, detail) {
  elements.connectionBadge.textContent = status;
  elements.connectionBadge.className = 'status-badge';
  if (status === 'CONNECTED') elements.connectionBadge.classList.add('status-connected');
  else if (status === 'CONNECTING') elements.connectionBadge.classList.add('status-busy');
  else if (status === 'ERROR') elements.connectionBadge.classList.add('status-error');
  else elements.connectionBadge.classList.add('status-idle');
  elements.connectionDetail.textContent = detail;
}

function setConnected(connected, transport = null) {
  state.connected = connected;
  state.transport = connected ? transport : null;
  elements.controlFieldset.disabled = !connected;
  elements.disconnectBtn.disabled = !connected;
  elements.connectBleBtn.disabled = connected || !('bluetooth' in navigator);
  elements.connectUsbBtn.disabled = connected || !('serial' in navigator);
  if (connected) {
    setConnectionStatus('CONNECTED', `${transport === 'ble' ? 'Bluetooth' : 'USB serial'} link active. Settings are sent only after you change them.`);
  } else {
    setConnectionStatus('DISCONNECTED', 'Choose a local connection. No internet is used after the app is cached.');
    state.receiveBuffer = '';
    state.deviceStateKnown = false;
    renderOutputState();
  }
}

function formatNumber(value, decimals = 2) {
  const numeric = Number.parseFloat(value);
  return Number.isFinite(numeric) ? numeric.toFixed(decimals) : '—';
}

function selectedWaveformButton() {
  return document.querySelector(`.segment[data-waveform="${state.waveform}"]`);
}

function setWaveform(waveform) {
  state.waveform = waveform;
  document.querySelectorAll('.segment').forEach((button) => {
    const active = button.dataset.waveform === waveform;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

function currentSettingsCommand() {
  return `F:${elements.frequencyNumber.value} A:${elements.amplitudeNumber.value} W:${state.waveform}\n`;
}

function scheduleSettings(immediate = false) {
  if (!state.connected) return;
  window.clearTimeout(state.settingsTimer);
  if (immediate) {
    sendCommand(currentSettingsCommand());
    return;
  }
  state.settingsTimer = window.setTimeout(() => sendCommand(currentSettingsCommand()), SETTINGS_DEBOUNCE_MS);
}

function flushSettings() {
  if (!state.connected) return;
  window.clearTimeout(state.settingsTimer);
  sendCommand(currentSettingsCommand());
}

function syncNumericInput(numberInput, rangeInput) {
  const minimum = Number.parseFloat(rangeInput.min);
  const maximum = Number.parseFloat(rangeInput.max);
  let value = Number.parseFloat(numberInput.value);
  if (!Number.isFinite(value)) value = Number.parseFloat(rangeInput.value);
  value = Math.min(maximum, Math.max(minimum, value));
  numberInput.value = String(value);
  rangeInput.value = String(value);
}

function renderTrim(userSteps) {
  const parsedSteps = Number.parseInt(userSteps, 10);
  const minimum = Number.parseInt(elements.offsetTrimRange.min, 10);
  const maximum = Number.parseInt(elements.offsetTrimRange.max, 10);
  const safeSteps = Math.max(minimum, Math.min(maximum, Number.isFinite(parsedSteps) ? parsedSteps : 0));
  const outputEquivalent = safeSteps * DAC_B_LSB_VOLTS * POWER_STAGE_GAIN;
  elements.offsetTrimRange.value = String(safeSteps);
  elements.offsetTrimValue.textContent = `${safeSteps} steps · ${outputEquivalent >= 0 ? '+' : ''}${outputEquivalent.toFixed(3)} V`;
  elements.statusManualTrim.textContent = `${safeSteps >= 0 ? '+' : ''}${safeSteps} steps (${outputEquivalent >= 0 ? '+' : ''}${outputEquivalent.toFixed(3)} V)`;
}

function scheduleTrim(immediate = false) {
  if (!state.connected) return;
  window.clearTimeout(state.trimTimer);
  // TRIM is a DAC-B code. The analog subtractor reverses its effect at the
  // output, so invert the user-facing output-offset correction here.
  const send = () => sendCommand(`TRIM:${-Number.parseInt(elements.offsetTrimRange.value, 10)}\n`);
  if (immediate) send();
  else state.trimTimer = window.setTimeout(send, TRIM_DEBOUNCE_MS);
}

function nudgeTrim(delta) {
  const current = Number.parseInt(elements.offsetTrimRange.value, 10);
  renderTrim(current + delta);
  scheduleTrim(true);
}

async function sendCommand(command) {
  if (!state.connected) {
    log('!', 'No transmitter connection.');
    return;
  }
  const printable = command.trim();
  state.writeQueue = state.writeQueue.then(async () => {
    log('>', printable);
    if (state.transport === 'ble') {
      const characteristic = state.ble.txCharacteristic;
      const data = new TextEncoder().encode(command);
      if (typeof characteristic.writeValueWithResponse === 'function') await characteristic.writeValueWithResponse(data);
      else await characteristic.writeValue(data);
    } else if (state.transport === 'serial') {
      await state.serial.writer.write(new TextEncoder().encode(command));
    }
  }).catch((error) => {
    log('!', `Write failed: ${error.message || error}`);
    setConnectionStatus('ERROR', 'The command could not be sent. Reconnect the transmitter.');
  });
  return state.writeQueue;
}

function appendIncoming(text) {
  state.receiveBuffer += text.replaceAll('\r', '');
  let newline = state.receiveBuffer.indexOf('\n');
  while (newline >= 0) {
    const message = state.receiveBuffer.slice(0, newline).trim();
    state.receiveBuffer = state.receiveBuffer.slice(newline + 1);
    if (message) {
      try {
        handleMessage(message);
      } catch (error) {
        log('!', `Message processing failed: ${error.message || error}`);
      }
    }
    newline = state.receiveBuffer.indexOf('\n');
  }
}

function handleMessage(message) {
  log('<', message);
  if (message.startsWith('BAT:')) parseBattery(message.slice(4));
  else if (message.startsWith('STATUS:')) parseStatus(message.slice(7));
  else if (message.startsWith('OK:') || message === 'OK') parseAcknowledgement(message);
}

function parseBattery(payload) {
  const [positive, negative, percent] = payload.split(',');
  const health = Number.parseInt(percent, 10);
  if (!Number.isFinite(health)) return;
  elements.positiveRail.textContent = formatNumber(positive);
  elements.negativeRail.textContent = formatNumber(negative);
  elements.batteryPercent.textContent = `${Math.max(0, Math.min(100, health))}%`;
  elements.batteryMeter.style.width = `${Math.max(0, Math.min(100, health))}%`;
  elements.batteryMeter.style.background = health < 20 ? 'var(--red)' : health < 50 ? 'var(--amber)' : 'var(--green)';
  state.lastTelemetryAt = Date.now();
  elements.telemetryAge.textContent = 'Live telemetry';
}

function renderBatteryUnavailable() {
  elements.positiveRail.textContent = '—';
  elements.negativeRail.textContent = '—';
  elements.batteryPercent.textContent = '—';
  elements.batteryMeter.style.width = '0%';
  elements.batteryMeter.style.background = 'var(--muted)';
  elements.telemetryAge.textContent = 'Battery telemetry unavailable';
}

function parseStatus(payload) {
  const fields = Object.fromEntries(payload.split(',').map((entry) => {
    const separator = entry.indexOf(':');
    return separator > 0 ? [entry.slice(0, separator), entry.slice(separator + 1)] : [entry, ''];
  }));
  if (fields.F) {
    elements.frequencyNumber.value = fields.F;
    elements.frequencyRange.value = fields.F;
  }
  if (fields.A) {
    elements.amplitudeNumber.value = fields.A;
    elements.amplitudeRange.value = fields.A;
  }
  if (fields.W === 'S' || fields.W === 'T') setWaveform(fields.W);
  // The device reports DAC-B codes; display their inverse output effect.
  if (fields.TRIM !== undefined) renderTrim(-Number.parseInt(fields.TRIM, 10));
  if (fields.BLT === '0' || fields.BLT === '1') elements.bluetoothSwitch.checked = fields.BLT === '1';
  if (fields.BATP && fields.BATN && fields.BAT) parseBattery(`${fields.BATP},${fields.BATN},${fields.BAT}`);
  else if (fields.BAT === 'UNAVAILABLE') renderBatteryUnavailable();
  elements.statusWaveform.textContent = fields.W === 'T' ? 'Triangle' : fields.W === 'S' ? 'Sine' : '—';
  elements.statusBluetooth.textContent = fields.BLT === '1' ? 'Advertising' : fields.BLT === '0' ? 'Off' : '—';
  state.deviceStateKnown = true;
  renderOutputState();
}

function parseAcknowledgement(message) {
  const amplitude = message.match(/:A:([\d.]+)/);
  if (amplitude) {
    elements.amplitudeNumber.value = amplitude[1];
    elements.amplitudeRange.value = amplitude[1];
    state.deviceStateKnown = true;
    renderOutputState();
  }
}

function renderOutputState() {
  elements.outputIndicator.className = 'output-indicator';
  if (!state.deviceStateKnown) {
    elements.outputIndicator.classList.add('is-unknown');
    elements.outputIndicator.textContent = 'OUTPUT UNKNOWN';
    return;
  }
  if (Number.parseFloat(elements.amplitudeNumber.value) > 0) {
    elements.outputIndicator.classList.add('is-on');
    elements.outputIndicator.textContent = 'OUTPUT ACTIVE';
  } else {
    elements.outputIndicator.classList.add('is-off');
    elements.outputIndicator.textContent = 'OUTPUT MUTED';
  }
}

async function connectBle() {
  if (!('bluetooth' in navigator)) return;
  setConnectionStatus('CONNECTING', 'Requesting a nearby FDEM transmitter…');
  try {
    const device = await navigator.bluetooth.requestDevice({ filters: [{ services: [NUS_SERVICE_UUID] }] });
    device.addEventListener('gattserverdisconnected', () => handleDisconnect('Bluetooth link disconnected.'));
    const server = await device.gatt.connect();
    const service = await server.getPrimaryService(NUS_SERVICE_UUID);
    const txCharacteristic = await service.getCharacteristic(NUS_RX_UUID);
    const rxCharacteristic = await service.getCharacteristic(NUS_TX_UUID);
    await rxCharacteristic.startNotifications();
    rxCharacteristic.addEventListener('characteristicvaluechanged', (event) => appendIncoming(new TextDecoder().decode(event.target.value)));
    state.ble = { device, txCharacteristic, rxCharacteristic };
    setConnected(true, 'ble');
    log('*', `Connected to ${device.name || 'BLE transmitter'}.`);
    sendCommand('STATUS\n');
  } catch (error) {
    setConnected(false);
    setConnectionStatus('ERROR', `Bluetooth connection failed: ${error.message || error}`);
    log('!', `Bluetooth connection failed: ${error.message || error}`);
  }
}

async function connectSerial() {
  if (!('serial' in navigator)) return;
  setConnectionStatus('CONNECTING', 'Choose the transmitter serial port…');
  try {
    const port = await navigator.serial.requestPort();
    await port.open({ baudRate: BAUD_RATE });
    state.serial.port = port;
    state.serial.writer = port.writable.getWriter();
    setConnected(true, 'serial');
    state.serial.readTask = readSerial(port);
    log('*', 'USB serial connected.');
    sendCommand('STATUS\n');
    sendCommand('TELEM:1\n');
  } catch (error) {
    await closeSerial();
    setConnected(false);
    setConnectionStatus('ERROR', `USB serial connection failed: ${error.message || error}`);
    log('!', `USB serial connection failed: ${error.message || error}`);
  }
}

async function readSerial(port) {
  const decoder = new TextDecoderStream();
  const pipeClosed = port.readable.pipeTo(decoder.writable).catch(() => undefined);
  const reader = decoder.readable.getReader();
  state.serial.reader = reader;
  try {
    while (state.connected && state.serial.port === port) {
      const { value, done } = await reader.read();
      if (done) break;
      appendIncoming(value);
    }
  } catch (error) {
    if (state.connected) log('!', `USB serial read error: ${error.message || error}`);
  } finally {
    reader.releaseLock();
    state.serial.reader = null;
    await pipeClosed;
    if (state.connected && state.transport === 'serial') handleDisconnect('USB serial link disconnected.');
  }
}

async function closeSerial() {
  const { port, writer, reader } = state.serial;
  try { if (reader) await reader.cancel(); } catch (_) { /* already closed */ }
  try { if (writer) writer.releaseLock(); } catch (_) { /* already released */ }
  try { if (port) await port.close(); } catch (_) { /* already closed */ }
  state.serial = { port: null, writer: null, reader: null, readTask: null };
}

async function disconnect() {
  if (!state.connected) return;
  const transport = state.transport;
  if (transport === 'ble') {
    try { if (state.ble.device?.gatt?.connected) state.ble.device.gatt.disconnect(); } catch (_) { /* browser has already disconnected */ }
    state.ble = { device: null, txCharacteristic: null, rxCharacteristic: null };
  } else {
    await closeSerial();
  }
  handleDisconnect('Disconnected by operator.');
}

function handleDisconnect(detail) {
  if (!state.connected) return;
  setConnected(false);
  log('*', detail);
}

function configureControls() {
  const pairedInputs = [
    [elements.frequencyNumber, elements.frequencyRange],
    [elements.amplitudeNumber, elements.amplitudeRange]
  ];
  pairedInputs.forEach(([numberInput, rangeInput]) => {
    rangeInput.addEventListener('input', () => { numberInput.value = rangeInput.value; scheduleSettings(); });
    rangeInput.addEventListener('change', flushSettings);
    numberInput.addEventListener('change', () => { syncNumericInput(numberInput, rangeInput); flushSettings(); });
  });
  document.querySelectorAll('.segment').forEach((button) => button.addEventListener('click', () => {
    setWaveform(button.dataset.waveform);
    scheduleSettings(true);
  }));
  elements.offsetTrimRange.addEventListener('input', () => {
    renderTrim(elements.offsetTrimRange.value);
    scheduleTrim();
  });
  elements.offsetTrimRange.addEventListener('change', () => scheduleTrim(true));
  elements.trimDecreaseBtn.addEventListener('click', () => nudgeTrim(-1));
  elements.trimIncreaseBtn.addEventListener('click', () => nudgeTrim(1));
  elements.bluetoothSwitch.addEventListener('change', () => {
    if (!elements.bluetoothSwitch.checked && state.transport === 'ble' &&
        !window.confirm('Disable Bluetooth advertising? You will need USB serial to enable advertising again after disconnecting.')) {
      elements.bluetoothSwitch.checked = true;
      return;
    }
    sendCommand(`BLT:${elements.bluetoothSwitch.checked ? 1 : 0}\n`);
  });
  elements.statusBtn.addEventListener('click', () => sendCommand('STATUS\n'));
  elements.helpBtn.addEventListener('click', () => sendCommand('HELP\n'));
  elements.clearLogBtn.addEventListener('click', () => { elements.logOutput.textContent = ''; });
}

function configurePwa() {
  if (!('serviceWorker' in navigator)) {
    setNotice(elements.offlineStatus, 'Offline cache unavailable in this browser', 'warning');
    return;
  }
  navigator.serviceWorker.register('./sw.js').then((registration) => {
    const showUpdate = () => {
      if (!registration.waiting) return;
      elements.updateBtn.hidden = false;
      setNotice(elements.offlineStatus, 'An update is ready; apply it when it is safe to reload.', 'warning');
    };
    registration.addEventListener('updatefound', () => {
      const worker = registration.installing;
      worker?.addEventListener('statechange', () => {
        if (worker.state === 'installed' && navigator.serviceWorker.controller) showUpdate();
      });
    });
    showUpdate();
    navigator.serviceWorker.ready.then(() => setNotice(elements.offlineStatus, 'Offline app shell ready', 'ready'));
  }).catch((error) => setNotice(elements.offlineStatus, `Offline cache error: ${error.message || error}`, 'warning'));
  elements.updateBtn.addEventListener('click', () => {
    navigator.serviceWorker.getRegistration().then((registration) => {
      if (!registration?.waiting) return;
      state.updateRequested = true;
      registration.waiting.postMessage({ type: 'SKIP_WAITING' });
    });
  });
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (state.updateRequested) window.location.reload();
  });
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    state.deferredInstallPrompt = event;
    elements.installBtn.hidden = false;
  });
  elements.installBtn.addEventListener('click', async () => {
    if (!state.deferredInstallPrompt) return;
    state.deferredInstallPrompt.prompt();
    await state.deferredInstallPrompt.userChoice;
    state.deferredInstallPrompt = null;
    elements.installBtn.hidden = true;
  });
  window.addEventListener('appinstalled', () => {
    elements.installBtn.hidden = true;
    log('*', 'Controller installed as an app.');
  });
}

function configureCapabilities() {
  const supported = [];
  if ('bluetooth' in navigator) supported.push('Bluetooth');
  else elements.connectBleBtn.disabled = true;
  if ('serial' in navigator) supported.push('USB serial');
  else elements.connectUsbBtn.disabled = true;
  const secure = window.isSecureContext;
  if (!secure) {
    elements.connectBleBtn.disabled = true;
    elements.connectUsbBtn.disabled = true;
    setNotice(elements.browserStatus, 'Open via HTTPS for Bluetooth and USB access', 'warning');
  } else if (supported.length === 2) {
    setNotice(elements.browserStatus, 'Chromium device APIs available', 'ready');
  } else if (supported.length) {
    setNotice(elements.browserStatus, `${supported.join(' and ')} available; some features are unavailable`, 'warning');
  } else {
    setNotice(elements.browserStatus, 'Use Chrome or Edge for transmitter control', 'warning');
  }
  elements.connectBleBtn.addEventListener('click', connectBle);
  elements.connectUsbBtn.addEventListener('click', connectSerial);
  elements.disconnectBtn.addEventListener('click', disconnect);
  navigator.serial?.addEventListener('disconnect', (event) => {
    if (event.target === state.serial.port) handleDisconnect('USB serial device disconnected.');
  });
  window.addEventListener('online', () => setNotice(elements.offlineStatus, 'Online; cached app remains available offline', 'ready'));
  window.addEventListener('offline', () => setNotice(elements.offlineStatus, 'Offline; local BLE and USB remain available', 'ready'));
}

configureControls();
configureCapabilities();
configurePwa();
setWaveform('S');
renderTrim(0);
renderOutputState();
