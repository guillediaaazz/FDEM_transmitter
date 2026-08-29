import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const appUrl = new URL('../assets/app.js', import.meta.url);
const htmlUrl = new URL('../index.html', import.meta.url);

function fakeElement(id) {
  return {
    id,
    value: '',
    min: '',
    max: '',
    textContent: '',
    className: '',
    checked: false,
    disabled: false,
    hidden: false,
    dataset: {},
    style: {},
    scrollHeight: 0,
    classList: { add() {}, toggle() {} },
    addEventListener() {},
    setAttribute() {}
  };
}

async function loadController() {
  const [app, html] = await Promise.all([
    readFile(appUrl, 'utf8'),
    readFile(htmlUrl, 'utf8')
  ]);
  const nodes = new Map(
    [...html.matchAll(/\bid="([^"]+)"/g)]
      .map((match) => [match[1], fakeElement(match[1])])
  );
  nodes.get('offsetTrimRange').min = '-255';
  nodes.get('offsetTrimRange').max = '255';
  nodes.get('offsetTrimRange').value = '0';
  nodes.get('frequencyNumber').value = '1000';
  nodes.get('frequencyRange').value = '1000';
  nodes.get('amplitudeNumber').value = '0';
  nodes.get('amplitudeRange').value = '0';

  const waveformButtons = ['S', 'T'].map((waveform) => {
    const button = fakeElement(`waveform-${waveform}`);
    button.dataset.waveform = waveform;
    return button;
  });
  const window = {
    isSecureContext: true,
    clearTimeout,
    setTimeout,
    addEventListener() {},
    confirm: () => true,
    location: { reload() {} }
  };
  const context = vm.createContext({
    console,
    document: {
      getElementById: (id) => nodes.get(id) ?? null,
      querySelectorAll: (selector) => selector === '.segment' ? waveformButtons : [],
      querySelector: () => null
    },
    navigator: {},
    TextDecoder,
    TextEncoder,
    window
  });
  vm.runInContext(`${app}\nglobalThis.__controllerTest = { appendIncoming, elements, nudgeTrim, renderTrim, state };`, context);
  return context.__controllerTest;
}

test('every controller element reference is declared and bound to an existing DOM id', async () => {
  const [app, html] = await Promise.all([
    readFile(appUrl, 'utf8'),
    readFile(htmlUrl, 'utf8')
  ]);

  const mapMatch = app.match(/const elements = \{([\s\S]*?)\n\};/);
  assert.ok(mapMatch, 'elements map was not found');

  const bindings = new Map(
    [...mapMatch[1].matchAll(/\b([A-Za-z_$][\w$]*)\s*:\s*\$\('([^']+)'\)/g)]
      .map((match) => [match[1], match[2]])
  );
  const references = new Set(
    [...app.matchAll(/\belements\.([A-Za-z_$][\w$]*)/g)]
      .map((match) => match[1])
  );
  const htmlIds = new Set(
    [...html.matchAll(/\bid="([^"]+)"/g)]
      .map((match) => match[1])
  );

  const undeclared = [...references].filter((name) => !bindings.has(name));
  assert.deepEqual(undeclared, [], `undeclared elements references: ${undeclared.join(', ')}`);

  const missingIds = [...bindings]
    .filter(([, id]) => !htmlIds.has(id))
    .map(([name, id]) => `${name} -> #${id}`);
  assert.deepEqual(missingIds, [], `element bindings without matching DOM ids: ${missingIds.join(', ')}`);
});

test('the page and service worker use the same controller asset version', async () => {
  const [html, serviceWorker] = await Promise.all([
    readFile(htmlUrl, 'utf8'),
    readFile(new URL('../sw.js', import.meta.url), 'utf8')
  ]);
  const pageVersion = html.match(/assets\/app\.js\?v=(\d+)/)?.[1];
  const cachedVersion = serviceWorker.match(/assets\/app\.js\?v=(\d+)/)?.[1];
  const cacheVersion = serviceWorker.match(/fdem-controller-v(\d+)/)?.[1];

  assert.ok(pageVersion, 'controller asset version was not found in index.html');
  assert.equal(cachedVersion, pageVersion);
  assert.equal(cacheVersion, pageVersion);
});

test('fragmented status updates output and battery, and trim buttons send inverted steps', async () => {
  const controller = await loadController();
  const writes = [];
  controller.state.connected = true;
  controller.state.transport = 'serial';
  controller.state.serial.writer = {
    write: async (data) => writes.push(new TextDecoder().decode(data))
  };

  controller.nudgeTrim(1);
  await controller.state.writeQueue;
  assert.equal(controller.elements.offsetTrimRange.value, '1');
  assert.equal(writes.at(-1), 'TRIM:-1\n');

  controller.renderTrim(0);
  controller.nudgeTrim(-1);
  await controller.state.writeQueue;
  assert.equal(controller.elements.offsetTrimRange.value, '-1');
  assert.equal(writes.at(-1), 'TRIM:1\n');

  controller.renderTrim(255);
  controller.nudgeTrim(1);
  await controller.state.writeQueue;
  assert.equal(controller.elements.offsetTrimRange.value, '255');
  assert.equal(writes.at(-1), 'TRIM:-255\n');

  controller.renderTrim(-255);
  controller.nudgeTrim(-1);
  await controller.state.writeQueue;
  assert.equal(controller.elements.offsetTrimRange.value, '-255');
  assert.equal(writes.at(-1), 'TRIM:255\n');

  controller.appendIncoming('STATUS:F:1000.00,A:4.000,W:S,TR');
  assert.equal(controller.state.deviceStateKnown, false);
  controller.appendIncoming('IM:-1,BLT:1,BATP:12.50,BATN:-12.40,BAT:87\n');
  assert.equal(controller.state.deviceStateKnown, true);
  assert.equal(controller.elements.outputIndicator.textContent, 'OUTPUT ACTIVE');
  assert.equal(controller.elements.batteryPercent.textContent, '87%');
  assert.equal(controller.elements.telemetryAge.textContent, 'Live telemetry');
});

test('a message rendering failure does not prevent the next telemetry line', async () => {
  const controller = await loadController();
  controller.elements.statusManualTrim = null;

  controller.appendIncoming(
    'STATUS:F:1000.00,A:0.000,W:S,TRIM:0,BLT:1,BAT:UNAVAILABLE\n' +
    'BAT:12.10,-12.00,64\n'
  );

  assert.equal(controller.elements.batteryPercent.textContent, '64%');
  assert.equal(controller.elements.telemetryAge.textContent, 'Live telemetry');
  assert.match(controller.elements.logOutput.textContent, /Message processing failed:/);
});
