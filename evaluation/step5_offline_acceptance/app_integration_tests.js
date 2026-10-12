/*
 * Step 5A：App API 整合測試（實際執行 App 的 TypeScript 原始碼，對真實修改後的 Gateway）
 *
 * - 以 App 自己的 typescript 套件即時轉譯 App 原始碼（services、contexts、screens），以 Node 執行。
 * - 後端：backend_harness.py 在 127.0.0.1 提供的「真實 Gateway v2」＋假序列埠。
 * - 測試替身（只限原生／裝置模組）：AsyncStorage（記憶體）、expo-constants、expo-linking、expo-router、
 *   expo-linear-gradient、safe-area、lucide 圖示、expo-speech；react-native → react-native-web（含 Alert 記錄）。
 * - 不是原生裝置或模擬器測試（另列 BLOCKED）。
 *
 * 用法：APP=consumer|farmer APP_ROOT=... TESTDEPS=... GW_URL=... CTL_URL=... RESULTS_OUT=... node app_integration_tests.js
 */
'use strict';
const Module = require('module');
const path = require('path');
const fs = require('fs');

const APP = process.env.APP;
const ROOT = path.resolve(process.env.APP_ROOT);
const TESTDEPS = path.resolve(process.env.TESTDEPS);
const GW = process.env.GW_URL;
const CTL = process.env.CTL_URL;
const OUT = process.env.RESULTS_OUT;
const ts = require(path.join(ROOT, 'node_modules/typescript'));

const origResolve = Module._resolveFilename;
// ── 測試替身 ──
const alerts = [];
const mem = new Map();
const AsyncStorage = {
  getItem: async (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: async (k, v) => { mem.set(k, String(v)); },
  removeItem: async (k) => { mem.delete(k); },
  multiRemove: async (ks) => { ks.forEach((k) => mem.delete(k)); },
  getAllKeys: async () => [...mem.keys()],
  clear: async () => mem.clear(),
};
let routeParams = {};
const routerStub = { push() {}, replace() {}, back() {}, navigate() {} };
const STUBS = {
  '@react-native-async-storage/async-storage': { __esModule: true, default: AsyncStorage },
  'expo-constants': { __esModule: true, default: { expoConfig: { version: '1.0.0-test' } } },
  'expo-linking': { __esModule: true, createURL: (p) => p },
  'expo-speech': { __esModule: true, speak() {}, stop() {} },
  'expo-haptics': { __esModule: true, impactAsync: async () => {}, notificationAsync: async () => {}, ImpactFeedbackStyle: {}, NotificationFeedbackType: {} },
};
function lazyStubs(React, RN) {
  const View = (p) => React.createElement(RN.View, p, p.children);
  return {
    'expo-router': { __esModule: true, useRouter: () => routerStub, router: routerStub, useLocalSearchParams: () => routeParams,
      Stack: Object.assign(() => null, { Screen: () => null }), Link: (p) => React.createElement(RN.Text, null, p.children) },
    'expo-linear-gradient': { __esModule: true, LinearGradient: View },
    'expo-blur': { __esModule: true, BlurView: View },
    'react-native-safe-area-context': { __esModule: true, useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }), SafeAreaView: View, SafeAreaProvider: View },
    'lucide-react-native': new Proxy({ __esModule: true }, { get: (t, k) => (k === '__esModule' ? true : () => null) }),
    'react-native-svg': new Proxy({ __esModule: true }, { get: (t, k) => (k === '__esModule' ? true : View) }),
  };
}

const APP_PARENT = { id: path.join(ROOT, '__step5__.js'), filename: path.join(ROOT, '__step5__.js'), paths: Module._nodeModulePaths(ROOT) };
function appResolve(req) { return origResolve.call(Module, req, APP_PARENT, false); }
let RNW = null;
function rnModule() {
  if (!RNW) {
    const real = require(appResolve('react-native-web'));
    RNW = { ...real, __esModule: true,
      Alert: { alert: (...a) => { alerts.push(a); } },
      Platform: { ...real.Platform, OS: 'android', select: (o) => (o.android ?? o.native ?? o.default) },
      BackHandler: { addEventListener: () => ({ remove() {} }) },
      UIManager: { setLayoutAnimationEnabledExperimental() {} },
      LayoutAnimation: { configureNext() {}, Presets: {}, create() {} } };
  }
  return RNW;
}
let LAZY = null;
Module._resolveFilename = function (request, parent, ...rest) {
  if (request === 'react' || request.startsWith('react/') || request === 'react-dom' || request.startsWith('react-dom/') ||
      request === 'scheduler' || request === 'react-is') {
    return origResolve.call(this, appResolve(request), parent, ...rest);
  }
  if (request === 'react-test-renderer') return origResolve.call(this, path.join(TESTDEPS, 'node_modules/react-test-renderer'), parent, ...rest);
  if (request.startsWith('@/')) return origResolve.call(this, path.join(ROOT, request.slice(2)), parent, ...rest);
  try { return origResolve.call(this, request, parent, ...rest); } catch (e) {
    // 測試程式本身 require App 的套件時，從 App 根目錄解析
    if (!request.startsWith('.') && !path.isAbsolute(request)) return appResolve(request);
    throw e;
  }
};
const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (STUBS[request]) return STUBS[request];
  if (request === 'react-native') return rnModule();
  if (request in OVERRIDES) return OVERRIDES[request];
  if (!LAZY && ['expo-router', 'expo-linear-gradient', 'expo-blur', 'react-native-safe-area-context', 'lucide-react-native', 'react-native-svg'].includes(request)) {
    LAZY = lazyStubs(require('react'), rnModule());
  }
  if (LAZY && LAZY[request]) return LAZY[request];
  return origLoad.call(this, request, parent, isMain);
};
const OVERRIDES = {};
for (const ext of ['.ts', '.tsx']) {
  require.extensions[ext] = function (m, filename) {
    const src = fs.readFileSync(filename, 'utf8');
    const out = ts.transpileModule(src, { fileName: filename, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } });
    m._compile(out.outputText, filename);
  };
}
// 只有 App 自己的原始碼需要以副檔名解析
const origFind = Module._findPath;
Module._findPath = function (request, paths, isMain) {
  const r = origFind.call(this, request, paths, isMain);
  if (r) return r;
  for (const ext of ['.ts', '.tsx', '/index.ts', '/index.tsx']) {
    if (path.isAbsolute(request) && fs.existsSync(request + ext)) return request + ext;
  }
  return false;
};
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
// Node 沒有動畫影格 API（測試環境用計時器代替；只影響 react-native-web 的 Animated）
globalThis.requestAnimationFrame = globalThis.requestAnimationFrame || ((cb) => setTimeout(() => cb(Date.now()), 16));
globalThis.cancelAnimationFrame = globalThis.cancelAnimationFrame || ((id) => clearTimeout(id));

// ── 結果紀錄 ──
const RESULTS = [];
function rec(id, name, ok, evidence, kind = 'RUNTIME (real App TS modules + real Gateway over loopback; fake serial)') {
  RESULTS.push({ app: APP, id, test: name, kind, verdict: ok ? 'PASS' : 'FAIL', evidence: String(evidence).slice(0, 500) });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${id} ${name} — ${String(evidence).slice(0, 220)}`);
}
async function check(id, name, fn, kind) {
  try { const [ok, ev] = await fn(); rec(id, name, ok, ev, kind); } catch (e) {
    const inner = e && e.errors ? ' :: ' + e.errors.map((x) => (x && x.stack ? x.stack.split('\n').slice(0, 3).join(' | ') : String(x))).join(' // ') : '';
    rec(id, name, false, `TEST ERROR ${e && e.message}${inner} @ ${e && e.stack ? e.stack.split('\n').slice(1, 3).join(' | ') : ''}`, kind);
  }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function ctl(p, body) {
  const r = await fetch(CTL + p, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.json();
}
async function waitFor(fn, ms = 20000, step = 20) {
  const end = Date.now() + ms;
  while (Date.now() < end) { const v = await fn(); if (v) return v; await sleep(step); }
  return null;
}
async function rejects(p) { try { await p; return '(resolved)'; } catch (e) { return e && e.message ? e.message : String(e); } }

// ── React 渲染輔助（真實 Provider） ──
function mountHook(React, TR, Providers, useHooks) {
  const box = { current: null };
  function Probe() { box.current = useHooks(); return null; }
  let el = React.createElement(Probe);
  for (const P of [...Providers].reverse()) el = React.createElement(P, null, el);
  let root;
  TR.act(() => { root = TR.create(el); });
  return { box, root };
}

async function consumer() {
  const React = require('react');
  const TR = require('react-test-renderer');
  const api = require('@/services/api');
  const storage = require('@/services/storage');
  const Sensor = require('@/contexts/SensorContext');
  const History = require('@/contexts/HistoryContext');
  const Calib = require('@/contexts/CalibrationContext');
  const { QueryClient, QueryClientProvider } = require('@tanstack/react-query');
  await AsyncStorage.setItem('@pineapple_api_url', GW);
  const setBase = (u) => AsyncStorage.setItem('@pineapple_api_url', u);

  // ── API client：正式模式 ──
  await check('APP-C01', '正式模式（出貨核准清單為空）：apiStartScan 回報 MODEL_NOT_APPROVED，不產生 scan_id', async () => {
    await ctl('/__ctl/reset', { mode: 'formal', registry: 'shipped', air: 'formal_live' });
    const msg = await rejects(api.apiStartScan());
    const ss = await ctl('/__ctl/serial_state');
    return [msg === 'MODEL_NOT_APPROVED' && ss.instances === 0, `apiStartScan → ${msg}; serial opened=${ss.instances}`];
  });

  // ── API client：工程（TEST）模式 ──
  await ctl('/__ctl/reset', { mode: 'engineering', registry: 'engineering', air: 'eng_live' });
  await check('APP-C02', '工程模式：apiStartScan → scan_id；apiGetStatus(scanId) 輪詢到 done；validateRpiResult 通過且為 TEST', async () => {
    const st = await api.apiStartScan();
    const done = await waitFor(async () => { const s = await api.apiGetStatus(st.scan_id); return s.status === 'done' ? s : null; });
    const r = Sensor.validateRpiResult(done.result, st.scan_id, st.result_kind);
    return [st.result_kind === 'TEST' && done.scan_id === st.scan_id && r.result_kind === 'TEST' && r.mode === 'engineering',
      `scan_id=${st.scan_id.slice(0, 8)} kind=${st.result_kind} status=${done.status} stage=${r.ripeness} model_status=${r.model_status}`];
  });
  await check('APP-C03', 'apiGetStatus 沒有 scan_id → Gateway 400 SCAN_ID_REQUIRED，App 拋出錯誤', async () => {
    const msg = await rejects(api.apiGetStatus(''));
    return [/HTTP 400|SCAN_ID_REQUIRED/.test(msg), msg];
  });
  await check('APP-C04', '設備忙碌：第二次 apiStartScan 拋出 DEVICE_BUSY（不去追蹤別人的掃描）', async () => {
    await ctl('/__ctl/serial', { lines: 'day:0', gate_after: 12 });
    const first = await api.apiStartScan();
    const msg = await rejects(api.apiStartScan());
    await api.apiCancelScan(first.scan_id);
    await ctl('/__ctl/gate', {});
    await waitFor(async () => (await ctl(`/__ctl/scan?scan_id=${first.scan_id}`)).released);
    return [msg === 'DEVICE_BUSY', `second start → ${msg}`];
  });
  await check('APP-C05', '已完成的舊 scan_id 只回自己的結果；拿舊結果對新 scan_id 驗證 → RESULT_SCAN_ID_MISMATCH', async () => {
    await ctl('/__ctl/serial', { lines: 'day:0' });
    const a = await api.apiStartScan();
    await waitFor(async () => (await api.apiGetStatus(a.scan_id)).status === 'done');
    await ctl('/__ctl/serial', { lines: 'day:1' });
    const b = await api.apiStartScan();
    await waitFor(async () => (await api.apiGetStatus(b.scan_id)).status === 'done');
    const sa = await api.apiGetStatus(a.scan_id);
    let msg = '(accepted)';
    try { Sensor.validateRpiResult(sa.result, b.scan_id, 'TEST'); } catch (e) { msg = e.message; }
    return [sa.result.scan_id === a.scan_id && msg === 'RESULT_SCAN_ID_MISMATCH', `status(old).result.scan_id==old: ${sa.result.scan_id === a.scan_id}; stale validate → ${msg}`];
  });
  await check('APP-C06', '連線失敗：apiStartScan 拋出錯誤（不產生結果）', async () => {
    await setBase('http://127.0.0.1:1');
    const msg = await rejects(api.apiStartScan());
    await setBase(GW);
    return [msg !== '(resolved)', msg];
  });
  for (const [id, variant, want] of [['APP-C07', 'noid', 'INCOMPLETE_RESPONSE'], ['APP-C08', 'html', 'INCOMPLETE_RESPONSE']]) {
    await check(id, `無效回應（${variant}）：apiStartScan → ${want}`, async () => {
      await setBase(`${CTL}/bad/${variant}`);
      const msg = await rejects(api.apiStartScan());
      await setBase(GW);
      return [msg === want, msg];
    });
  }

  // ── SensorContext（真實 Provider 與 hook）──
  const sensor = mountHook(React, TR, [Sensor.SensorProvider], () => Sensor.useSensor());
  const S = () => sensor.box.current;
  await check('APP-C09', 'SensorContext.startScan（工程模式）：結果帶 scanId、resultKind=TEST；環境值來自量測', async () => {
    await ctl('/__ctl/serial', { lines: 'day:0' });
    let r; await TR.act(async () => { r = await S().startScan(); });
    return [r.resultKind === 'TEST' && typeof r.scanId === 'string' && r.scanId.length === 32 && r.processedData.temperature !== 25,
      `resultKind=${r.resultKind} scanId=${r.scanId.slice(0, 8)} ripeness=${r.ripeness} temp=${r.processedData.temperature} humidity=${r.processedData.humidity}`];
  });
  await check('APP-C10', 'SensorContext：感測列沒有環境值 → temperature／humidity／pressure 為 null（不填 25／65／1013）', async () => {
    await ctl('/__ctl/serial', { lines: 'day:0', blank_env: true });
    let r; await TR.act(async () => { r = await S().startScan(); });
    const p = r.processedData, raw = r.rawData;
    return [p.temperature === null && p.humidity === null && p.pressure === null && raw.Temp_C === null && raw.Pressure_hPa === null,
      `processed=${JSON.stringify({ t: p.temperature, h: p.humidity, p: p.pressure })} raw.Temp_C=${raw.Temp_C}`];
  });
  for (const bad of ['nan', 'inf', 'range', 'missing']) {
    await check(`APP-C11-${bad.toUpperCase()}`, `SensorContext：ADC ${bad} → startScan 失敗（ADC_INVALID），不寫入 TEST 歷史`, async () => {
      const before = (await ctl('/__ctl/history?kind=TEST')).length;
      await ctl('/__ctl/serial', { lines: 'day:0', bad });
      let msg; await TR.act(async () => { msg = await rejects(S().startScan()); });
      const after = (await ctl('/__ctl/history?kind=TEST')).length;
      return [msg === 'ADC_INVALID' && after === before, `startScan → ${msg}; history_test ${before}→${after}`];
    });
  }
  await check('APP-C12', 'SensorContext：掃描中 cancelCurrentScan → startScan 失敗、Gateway 狀態 cancelled、不寫入、序列埠關閉', async () => {
    const before = (await ctl('/__ctl/history?kind=TEST')).length;
    await ctl('/__ctl/serial', { lines: 'day:0', gate_after: 12 });
    let p; await TR.act(async () => { p = rejects(S().startScan()); await sleep(50); });
    await waitFor(async () => (await ctl('/__ctl/serial_state')).calls[0] > 12);
    const hist = await ctl('/__ctl/history?kind=FAILED');
    await TR.act(async () => { await S().cancelCurrentScan(); });
    let msg; await TR.act(async () => { msg = await p; });
    const ss = await ctl('/__ctl/serial_state');
    await ctl('/__ctl/gate', {});
    const fails = (await ctl('/__ctl/history?kind=FAILED')).filter((x) => x.status === 'cancelled').length - hist.filter((x) => x.status === 'cancelled').length;
    const after = (await ctl('/__ctl/history?kind=TEST')).length;
    return [msg === 'SCAN_CANCELLED' && after === before && fails === 1 && ss.closed[0] === true,
      `startScan → ${msg}; gateway cancelled records +${fails}; history_test ${before}→${after}; serial closed=${ss.closed[0]}`];
  });
  await check('APP-C13', 'SensorContext：輪詢逾時（120 s，以假 Date.now 推進）→ SCAN_TIMEOUT，並對 Gateway 送出取消', async () => {
    await ctl('/__ctl/serial', { lines: 'day:0', gate_after: 12 });
    const realNow = Date.now; let offset = 0; Date.now = () => realNow() + offset;
    let p; await TR.act(async () => { p = rejects(S().startScan()); await sleep(50); });
    await waitFor(async () => (await ctl('/__ctl/serial_state')).calls[0] > 12);
    offset = 130000;
    let msg; await TR.act(async () => { msg = await p; });
    Date.now = realNow;
    const fails = await ctl('/__ctl/history?kind=FAILED');
    await ctl('/__ctl/gate', {});
    const last = fails[fails.length - 1];
    return [msg === 'SCAN_TIMEOUT' && last && last.status === 'cancelled', `startScan → ${msg}; gateway last failure=${last && last.status}/${last && last.reason_code}`];
  });
  await check('APP-C14', 'SensorContext：後端回傳不完整的 done 結果 → INCOMPLETE_RESPONSE（不顯示成熟度）', async () => {
    await setBase(`${CTL}/bad/fakedone`);
    let msg; await TR.act(async () => { msg = await rejects(S().startScan()); });
    await setBase(GW);
    return [msg === 'INCOMPLETE_RESPONSE', `startScan → ${msg}`];
  });
  await check('APP-C15', 'validateRpiResult：measurement_valid=false／機率非有限／argmax 不一致 → 拒絕', async () => {
    await ctl('/__ctl/serial', { lines: 'day:0' });
    const st = await api.apiStartScan();
    const done = await waitFor(async () => { const s = await api.apiGetStatus(st.scan_id); return s.status === 'done' ? s : null; });
    const base = done.result; const out = [];
    for (const [name, mut] of [['measurement_valid=false', (r) => ({ ...r, measurement_valid: false })],
      ['NaN probability', (r) => ({ ...r, probabilities: { ...r.probabilities, stage0: NaN } })],
      ['argmax mismatch', (r) => ({ ...r, ripeness: ['unripe', 'transition', 'ripe', 'overripe'].find((x) => x !== r.ripeness) })],
      ['result_kind FORMAL on TEST scan', (r) => ({ ...r, result_kind: 'FORMAL' })]]) {
      try { Sensor.validateRpiResult(mut(base), st.scan_id, 'TEST'); out.push(`${name}:accepted`); } catch (e) { out.push(`${name}:${e.message}`); }
    }
    return [out.every((x) => !x.endsWith(':accepted')), out.join('; ')];
  });

  // ── CalibrationContext ──
  await check('APP-C16', 'CalibrationContext：正式模式校正以 scan_id 追蹤到 done；Gateway 寫入一筆校正紀錄', async () => {
    await ctl('/__ctl/reset', { mode: 'formal', registry: 'shipped', air: 'none' });
    await ctl('/__ctl/serial', { lines: 'air:0' });
    const c = mountHook(React, TR, [Calib.CalibrationProvider], () => Calib.useCalibration());
    await TR.act(async () => { await c.box.current.start(); });
    const ok = await waitFor(async () => !c.box.current.isCalibrating, 30000, 100);
    const cal = await ctl('/__ctl/history?kind=CALIBRATION');
    const err = c.box.current.lastError;
    TR.act(() => c.root.unmount());
    return [ok && err === null && cal.length === 1 && cal[0].source === 'live' && cal[0].mode === 'formal' && cal[0].device_id === null,
      `finished=${!!ok} lastError=${err} calibration records=${cal.length} meta={source:${cal[0] && cal[0].source}, mode:${cal[0] && cal[0].mode}, device_id:${cal[0] && cal[0].device_id}}`];
  });
  await check('APP-C17', 'CalibrationContext：連不到後端 → 顯示「空氣校正失敗」，不本地倒數假裝完成', async () => {
    await setBase('http://127.0.0.1:1');
    const n0 = alerts.length;
    const c = mountHook(React, TR, [Calib.CalibrationProvider], () => Calib.useCalibration());
    await TR.act(async () => { await c.box.current.start(); });
    const st = { isCalibrating: c.box.current.isCalibrating, lastError: c.box.current.lastError };
    TR.act(() => c.root.unmount());
    await setBase(GW);
    const a = alerts.slice(n0).map((x) => x[0]);
    return [!st.isCalibrating && st.lastError && a.includes('空氣校正失敗'), `isCalibrating=${st.isCalibrating} lastError=${st.lastError} alerts=${JSON.stringify(a)}`];
  });

  // ── History／storage：TEST 與正式分開 ──
  await ctl('/__ctl/reset', { mode: 'engineering', registry: 'engineering', air: 'eng_live' });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const QP = (p) => React.createElement(QueryClientProvider, { client: qc }, p.children);
  const hist = mountHook(React, TR, [QP, History.HistoryProvider], () => History.useHistory());
  const H = () => hist.box.current;
  await TR.act(async () => { await sleep(50); });
  await check('APP-C18', 'TEST 結果存入獨立的本機 TEST 紀錄；正式清單不含；uploadRecord 不會送到 Gateway', async () => {
    await ctl('/__ctl/serial', { lines: 'day:0' });
    const st = await api.apiStartScan();
    const done = await waitFor(async () => { const s = await api.apiGetStatus(st.scan_id); return s.status === 'done' ? s : null; });
    const raw = { MQ2_raw: 1, MQ3_raw: 1, MQ9_raw: 1, MQ135_raw: 1, TGS2602_raw: 1, Temp_C: null, Humidity_pct: null, Pressure_hPa: null };
    let recd; await TR.act(async () => { recd = await H().createAndSaveRecord(raw, done.result.ripeness, 'zh', {}, done.result.confidence, 'rpi-v1', st.scan_id, 'TEST'); });
    const formal = await storage.listRecords();
    const test = await storage.listTestRecords();
    await TR.act(async () => { try { await H().uploadRecord(recd.local_id); } catch { /* expected */ } await sleep(100); });
    const upT = await ctl('/__ctl/history?kind=UPLOAD_TEST'); const upF = await ctl('/__ctl/history?kind=UPLOAD_FORMAL');
    const msg = await rejects(api.uploadHistoryRecord(recd));
    return [formal.length === 0 && test.length === 1 && test[0].result_kind === 'TEST' && upT.length === 0 && upF.length === 0 && msg === 'TEST_RECORD_NOT_UPLOADABLE',
      `formal list=${formal.length} test list=${test.length} gateway uploads test/formal=${upT.length}/${upF.length} direct upload → ${msg}`];
  });
  await check('APP-C19', '建立紀錄必須有 scan_id、result_kind 與信心值（不補 0.7）', async () => {
    const raw = { MQ2_raw: 1, MQ3_raw: 1, MQ9_raw: 1, MQ135_raw: 1, TGS2602_raw: 1, Temp_C: null, Humidity_pct: null, Pressure_hPa: null };
    const a = await rejects(H().createAndSaveRecord(raw, 'ripe', 'zh', {}, 0.5, 'rpi-v1', undefined, 'TEST'));
    const b = await rejects(H().createAndSaveRecord(raw, 'ripe', 'zh', {}, undefined, 'rpi-v1', 'sid', 'TEST'));
    const c = await rejects(H().createAndSaveRecord(raw, 'ripe', 'zh', {}, 0.5, 'rpi-v1', 'sid', undefined));
    return [a === 'RECORD_MISSING_SCAN_ID_OR_KIND' && b === 'RECORD_MISSING_CONFIDENCE' && c === 'RECORD_MISSING_SCAN_ID_OR_KIND', `${a}; ${b}; ${c}`];
  });
  await check('APP-C20', '正式紀錄若 scan_id 未在後端提交 → 上傳被 Gateway 拒絕（SCAN_NOT_COMMITTED），不會進入後端歷史', async () => {
    const raw = { MQ2_raw: 1, MQ3_raw: 1, MQ9_raw: 1, MQ135_raw: 1, TGS2602_raw: 1, Temp_C: null, Humidity_pct: null, Pressure_hPa: null };
    let recd; await TR.act(async () => { recd = await H().createAndSaveRecord(raw, 'ripe', 'zh', {}, 0.5, 'rpi-v1', 'never-committed-scan', 'FORMAL'); });
    const msg = await rejects(api.uploadHistoryRecord(recd));
    const formal = await storage.listRecords();
    const upF = await ctl('/__ctl/history?kind=UPLOAD_FORMAL');
    return [/409/.test(msg) && formal.length === 1 && upF.length === 0, `upload → ${msg}; local formal list=${formal.length}; gateway uploads_formal=${upF.length}`];
  });
  await check('APP-C21', '舊上傳佇列（uploadScanRecord）不接受 TEST 或缺 scan_id 的資料', async () => {
    const a = await rejects(api.uploadScanRecord({ result_kind: 'TEST', scan_id: 'x' }));
    const b = await rejects(api.uploadScanRecord({ result_kind: 'FORMAL', scan_id: '' }));
    return [a === 'TEST_RECORD_NOT_UPLOADABLE' && b === 'TEST_RECORD_NOT_UPLOADABLE', `${a}; ${b}`];
  });
  TR.act(() => { hist.root.unmount(); sensor.root.unmount(); });

  // ── 掃描畫面（app/processing.tsx）：離開畫面時取消 ──
  await check('APP-C23', '掃描畫面：掃描中離開（unmount）→ App 呼叫 /cancel，Gateway 狀態 cancelled、不寫入 TEST 歷史', async () => {
    await ctl('/__ctl/reset', { mode: 'engineering', registry: 'engineering', air: 'eng_live' });
    await ctl('/__ctl/serial', { lines: 'day:0', gate_after: 12 });
    const { translations } = require('@/constants/translations');
    OVERRIDES['@/contexts/LanguageContext'] = { __esModule: true, useLanguage: () => ({ t: (k) => translations.zh[k] ?? k, language: 'zh' }) };
    OVERRIDES['@/contexts/TriviaContext'] = { __esModule: true, useTrivia: () => ({ continueSession() {}, stopSession() {} }) };
    OVERRIDES['@/components/PineappleTriviaCard'] = { __esModule: true, PineappleTriviaCard: () => null };
    const Processing = require(path.join(ROOT, 'app/processing.tsx')).default;
    let r;
    await TR.act(async () => { r = TR.create(React.createElement(Sensor.SensorProvider, null, React.createElement(Processing))); await sleep(100); });
    await waitFor(async () => { const s = await ctl('/__ctl/serial_state'); return s.calls[0] > 12; });
    const before = (await ctl('/__ctl/history?kind=FAILED')).length;
    await TR.act(async () => { r.unmount(); await sleep(300); });
    const fails = (await ctl('/__ctl/history?kind=FAILED')).slice(before);
    await ctl('/__ctl/gate', {});
    const testHist = await ctl('/__ctl/history?kind=TEST');
    for (const k of ['@/contexts/LanguageContext', '@/contexts/TriviaContext', '@/components/PineappleTriviaCard']) delete OVERRIDES[k];
    return [fails.length === 1 && fails[0].status === 'cancelled' && testHist.length === 0, `after unmount: gateway failure records=${JSON.stringify(fails.map((x) => x.status + '/' + x.reason_code))}; history_test=${testHist.length}`];
  }, 'RUNTIME (real app/processing.tsx + real SensorProvider; language/trivia contexts stubbed)');

  // ── 結果頁（app/result.tsx，react-native-web 伺服器端渲染）──
  const { translations } = require('@/constants/translations');
  const zh = (k) => translations.zh[k] ?? k;
  const mkResult = (kind, env) => ({
    id: 'sid', scanId: 'sid', resultKind: kind, ripeness: 'ripe', ripenessLabelZh: '成熟', ripenessLabelEn: 'Ripe', confidence: 0.6, metadata: {},
    rawData: { MQ2_raw: 1, MQ3_raw: 1, MQ9_raw: 1, MQ135_raw: 1, TGS2602_raw: 1, Temp_C: env, Humidity_pct: env, Pressure_hPa: env },
    processedData: { alcoholLevel: 1, odorIntensity: 1, airQuality: 1, smokeFlammable: 1, carbonMonoxide: 1, temperature: env, humidity: env, pressure: env },
    probabilities: { stage0: 0.1, stage1: 0.1, stage2: 0.6, stage3: 0.2 }, suggestions: [], maturityPercent: 60, timestamp: new Date().toISOString() });
  let currentResult = null;
  OVERRIDES['@/contexts/SensorContext'] = { __esModule: true, useSensor: () => ({ currentResult, submitFeedback() {}, clearResult() {} }) };
  OVERRIDES['@/contexts/LanguageContext'] = { __esModule: true, useLanguage: () => ({ t: zh, language: 'zh' }) };
  OVERRIDES['@/contexts/HistoryContext'] = { __esModule: true, useHistory: () => ({ createAndSaveRecord: async () => ({ local_id: 'x' }), uploadRecord: async () => {} }) };
  OVERRIDES['@/contexts/UploadQueueContext'] = { __esModule: true, useUploadQueue: () => ({}) };
  for (const k of Object.keys(require.cache)) if (k.includes(`${path.sep}app${path.sep}result.tsx`)) delete require.cache[k];
  const ResultScreen = require(path.join(ROOT, 'app/result.tsx')).default;
  const textOf = (r) => { const out = []; const walk = (n) => { if (n == null) return; if (typeof n === 'string') { out.push(n); return; }
    if (Array.isArray(n)) { n.forEach(walk); return; } (n.children || []).forEach(walk); }; walk(r.toJSON()); return JSON.stringify(out); };
  async function renderResult(kind, env) {
    currentResult = mkResult(kind, env);
    let r; await TR.act(async () => { r = TR.create(React.createElement(ResultScreen)); await sleep(20); });
    const label = r.root.findAll((n) => n.props && n.props.children === zh('detailedData'))[0];
    let toggle = label; while (toggle && typeof toggle.props.onPress !== 'function') toggle = toggle.parent;
    await TR.act(async () => { toggle.props.onPress(); await sleep(20); });
    const txt = textOf(r);
    TR.act(() => r.unmount());
    return txt;
  }
  await check('APP-C22', '結果頁：TEST 結果顯示「TEST（工程測試結果，非正式判定）」；正式結果不顯示；展開詳細資料後環境值缺失顯示「—」', async () => {
    const t = await renderResult('TEST', null);
    const f = await renderResult('FORMAL', 24.5);
    const badge = 'TEST（工程測試結果，非正式判定）';
    const nullEnv = /"—","°C"|"—°C"/.test(t), measured = /"24.5","°C"|"24.5°C"/.test(f);
    return [t.includes(badge) && !f.includes(badge) && nullEnv && measured && !/"25","°C"/.test(t),
      `TEST page badge=${t.includes(badge)}; FORMAL page badge=${f.includes(badge)}; null env shows —=${nullEnv}; measured env shown=${measured}`];
  }, 'RUNTIME (real app/result.tsx rendered with react-test-renderer + react-native-web; details toggle pressed; contexts stubbed to supply the result)');
}

async function farmer() {
  const React = require('react');
  const TR = require('react-test-renderer');
  const fapi = require('@/services/api');
  const store = require('@/store/app-store');
  await check('APP-F01', 'Farmer services/api.startScan：拋出 FARMER_SENSOR_NOT_CONNECTED（無 mock、無隨機、無預設值）', async () => {
    const msg = await rejects(fapi.startScan(GW));
    return [msg === 'FARMER_SENSOR_NOT_CONNECTED', msg];
  });
  await check('APP-F02', 'Farmer pingServer 對真實 Gateway：Gateway 沒有 /ping → false（Farmer 與 Gateway 沒有可用的掃描契約）', async () => {
    const ok = await fapi.pingServer(GW);
    return [ok === false, `pingServer(${GW}) → ${ok}`];
  });
  // 真實 AppProvider＋BatchScanScreen
  const Scan = require('@/screens/BatchScanScreen').default;
  const Summary = require('@/screens/BatchSummaryScreen').default;
  let api_ = null;
  function Capture() { api_ = store.useAppStore(); return null; }
  let root;
  await TR.act(async () => { root = TR.create(React.createElement(store.AppProvider, null, React.createElement(Capture))); });
  let batch;
  await TR.act(async () => { batch = api_.createBatch({ name: 'B-test', date: '2026-10-12', block: 'A', cultivar: 'MD2', harvest_count: 100, purpose: 'export', target_samples: 5 }); });
  routeParams = { batchId: batch.batch_id };
  await check('APP-F03', 'Farmer 批次掃描畫面：按下掃描 → 提示「無法掃描」，不建立樣本、不顯示成熟度／糖度／風險／信心值', async () => {
    let r;
    await TR.act(async () => { root.update(React.createElement(store.AppProvider, null, React.createElement(Capture))); });
    await TR.act(async () => { r = TR.create(React.createElement(store.AppProvider, null, React.createElement(() => { api_ = store.useAppStore(); return null; }), React.createElement(Scan))); });
    // 新的 Provider 實例沒有剛建立的批次 → 在同一個 Provider 內建立
    let b2; await TR.act(async () => { b2 = api_.createBatch({ name: 'B-test', date: '2026-10-12', block: 'A', cultivar: 'MD2', harvest_count: 100, purpose: 'export', target_samples: 5 }); });
    routeParams = { batchId: b2.batch_id };
    await TR.act(async () => { r.update(React.createElement(store.AppProvider, null, React.createElement(() => { api_ = store.useAppStore(); return null; }), React.createElement(Scan))); });
    const n0 = alerts.length;
    const btn = r.root.findAll((n) => n.props && n.props.testID === 'scan-btn' && typeof n.props.onPress === 'function')[0];
    await TR.act(async () => { await btn.props.onPress(); });
    const a = alerts.slice(n0);
    const text = JSON.stringify(r.toJSON());
    const samples = api_.samples.filter((s) => s.batch_id === b2.batch_id).length;
    return [a.length === 1 && a[0][0] === '無法掃描' && samples === 0 && !/Brix|糖度：|信心/.test(a[0][1] || '') && text.includes('不會產生成熟度'),
      `alert=${JSON.stringify(a.map((x) => x[0]))} samples=${samples} screen notice shown=${text.includes('不會產生成熟度')}`];
  }, 'RUNTIME (real BatchScanScreen + real AppProvider, react-test-renderer with react-native-web; Alert recorded)');
  await check('APP-F04', 'Farmer 批次摘要：沒有樣本時平均糖度顯示「—」，不顯示 0.0 Brix', async () => {
    let r; await TR.act(async () => { r = TR.create(React.createElement(store.AppProvider, null, React.createElement(() => { api_ = store.useAppStore(); return null; }), React.createElement(Summary))); });
    let b3; await TR.act(async () => { b3 = api_.createBatch({ name: 'B-sum', date: '2026-10-12', block: 'A', cultivar: 'MD2', harvest_count: 10, purpose: 'export', target_samples: 5 }); });
    routeParams = { batchId: b3.batch_id };
    await TR.act(async () => { r.update(React.createElement(store.AppProvider, null, React.createElement(() => { api_ = store.useAppStore(); return null; }), React.createElement(Summary))); });
    const text = JSON.stringify(r.toJSON());
    return [text.includes('"—"') && !text.includes('"0.0"'), `summary shows —=${text.includes('"—"')} shows 0.0=${text.includes('"0.0"')}`];
  }, 'RUNTIME (real BatchSummaryScreen + real AppProvider)');
}

async function validatePayloads() {
  // 完整重播的每一筆 Gateway /status 回應，交給 Consumer App 真實的 validateRpiResult 驗證
  const Sensor = require('@/contexts/SensorContext');
  const items = JSON.parse(fs.readFileSync(process.env.VALIDATE_PAYLOADS, 'utf8'));
  const bad = [];
  for (const it of items) {
    try {
      if (it.status.scan_id !== it.scan_id) throw new Error('RESULT_SCAN_ID_MISMATCH');
      const r = Sensor.validateRpiResult(it.status.result, it.scan_id, it.result_kind);
      if (r.result_kind !== 'TEST') throw new Error('NOT_TEST');
    } catch (e) { bad.push(`${it.fruit_day}:${e.message}`); }
  }
  rec('APP-C30', `完整重播 ${items.length} 筆 Gateway 回應都通過 Consumer App 的 validateRpiResult（結果類型 TEST）`, bad.length === 0 && items.length > 0,
    `${items.length - bad.length}/${items.length} accepted; rejected=${bad.slice(0, 5).join(', ')}`, 'RUNTIME (real App validation code on real Gateway replay payloads)');
}

(async () => {
  try {
    if (process.env.VALIDATE_PAYLOADS) await validatePayloads();
    else if (APP === 'consumer') await consumer(); else await farmer();
  } catch (e) {
    rec(`${APP.toUpperCase()}-HARNESS`, 'harness', false, e && e.stack ? e.stack.split('\n').slice(0, 4).join(' | ') : e);
  }
  fs.writeFileSync(OUT, JSON.stringify(RESULTS, null, 1), 'utf8');
  const fail = RESULTS.filter((r) => r.verdict !== 'PASS').length;
  console.log(`${APP}: ${RESULTS.length - fail}/${RESULTS.length} PASS`);
  process.exit(fail ? 1 : 0);
})();
