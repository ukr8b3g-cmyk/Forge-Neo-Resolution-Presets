const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../javascript/forge_neo_resolution_presets_settings.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const copy = value => JSON.parse(JSON.stringify(value));

// Run the entire product script and its actual event handlers. Only DOM/fetch
// are simulated; no product state, validation or save logic is reimplemented.
async function setup(names = ['Test']) {
  const nodes = new Map();
  const node = () => ({dataset: {}, value: '', hidden: true, checked: false,
    disabled: false, events: {}, isConnected: true, textContent: '', innerHTML: '',
    appendChild(x) { this.textContent += x.textContent || ''; },
    addEventListener(k, f) { this.events[k] = f; }, focus() {}, querySelector() { return null; }});
  const root = node();
  root.querySelector = selector => {
    if (!nodes.has(selector)) nodes.set(selector, node());
    return nodes.get(selector);
  };
  let saved = {profiles: {default_profile: names[0], profiles: names.map(name => ({name,
    presets: [{width: 1024, height: 1024}]}))}, behavior: {}, history: [{width: 512, height: 512}], backups: []};
  const requests = [];
  const windowEvents = {};
  let hold = null, release = null, fail = false;
  const document = {addEventListener() {}, querySelectorAll() { return [root]; },
    createTextNode(text) { return {textContent: text}; }, createElement: node, readyState: 'complete'};
  vm.runInNewContext(source, {document, window: {addEventListener(k, f) { windowEvents[k] = f; }},
    onUiLoaded: f => f(), onAfterUiUpdate() {}, confirm: () => true,
    fetch: async (url, opts) => {
      const route = url.split('/settings/')[1];
      requests.push({route, body: opts.body && JSON.parse(opts.body)});
      const rejected = route === 'profiles' && fail;
      if (route === 'profiles' && !rejected) saved.profiles = JSON.parse(opts.body);
      if (route === 'history/clear') saved.history = [];
      if (route === 'profiles' || route === 'backup') saved.backups = ['profiles-backup.json'];
      const body = rejected ? {ok: false, message: 'Profile名が重複しています'} : {ok: true, state: copy(saved)};
      if (route === hold) {
        hold = null;
        await new Promise(resolve => { release = resolve; });
      }
      return {ok: !rejected, json: async () => body};
    }});
  await flush();
  const button = action => root.querySelector(`[data-action="${action}"]`);
  const click = action => {
    const target = button(action);
    target.dataset.index = '0';
    target.dataset.action = action;
    return root.events.click({target: {closest: () => target}});
  };
  return {nodes, requests, click, button,
    edit(value) { root.events.input({target: {value: String(value), dataset: {field: 'width'},
      closest: () => ({dataset: {index: '0'}})}}); },
    select(index) { const n = nodes.get('#fnp-settings-profile'); n.value = String(index); n.events.change(); },
    async create(name) { await click('add-profile'); nodes.get('#fnp-settings-profile-name').value = name; await click('create-profile'); },
    hold(route = 'profiles') { hold = route; }, release() { assert(release); release(); },
    rejectSave() { fail = true; }, allowSave() { fail = false; },
    get post() { return requests.filter(r => r.route === 'profiles'); },
    get status() { return nodes.get('#fnp-settings-status'); },
    get dirty() {
      let prevented = false;
      windowEvents.beforeunload({preventDefault() { prevented = true; }});
      return prevented;
    },
    get list() { return nodes.get('#fnp-settings-presets').innerHTML; }};
}

test('history clear preserves edited values, selection and dirty state', async () => {
  const h = await setup(['One', 'Two']); h.select(1); h.edit(1280);
  await h.click('clear-history');
  assert.match(h.status.className, /dirty$/);
  assert.equal(h.dirty, true);
  assert.equal(h.nodes.get('#fnp-settings-profile').value, '1');
  await h.click('save-profiles');
  assert.equal(h.post[0].body.profiles[1].presets[0].width, 1280);
});
test('history clear preserves added and deleted profiles', async () => {
  const h = await setup(['One', 'Two']); await h.create('Three');
  h.select(1); await h.click('delete-profile'); await h.click('clear-history'); await h.click('save-profiles');
  assert.deepEqual(h.post[0].body.profiles.map(p => p.name), ['One', 'Three']);
});
test('history clear preserves preset deletion undo', async () => {
  const h = await setup(); await h.click('add-preset'); await h.click('delete-preset');
  await h.click('clear-history');
  assert.match(h.status.textContent, /Undo/);
  await h.click('undo-delete'); await h.click('save-profiles');
  assert.equal(h.post[0].body.profiles[0].presets.length, 2);
});
test('late history response preserves edits made while awaiting it', async () => {
  const h = await setup(); h.hold('history/clear'); const clearing = h.click('clear-history');
  await flush(); h.edit(1536); h.release(); await clearing; await h.click('save-profiles');
  assert.equal(h.post[0].body.profiles[0].presets[0].width, 1536);
});
test('save response preserves newer edits; next save sends them', async () => {
  const h = await setup(); h.edit(1280); h.hold(); const saving = h.click('save-profiles');
  await flush(); h.edit(1536); h.release(); await saving;
  assert.match(h.status.className, /dirty$/);
  assert.equal(h.post[0].body.profiles[0].presets[0].width, 1280);
  await h.click('save-profiles'); assert.equal(h.post[1].body.profiles[0].presets[0].width, 1536);
  assert.match(h.status.className, /saved$/);
});
test('save response preserves profile addition and deletion made during save', async () => {
  const h = await setup(['One', 'Two']); h.hold(); const saving = h.click('save-profiles');
  await flush(); await h.create('Three'); h.select(1); await h.click('delete-profile');
  h.release(); await saving; assert.match(h.status.className, /dirty$/);
  await h.click('save-profiles'); assert.deepEqual(h.post[1].body.profiles.map(p => p.name), ['One', 'Three']);
});
test('concurrent saves and restores are blocked until completion', async () => {
  const h = await setup(); h.hold(); const saving = h.click('save-profiles'); await flush();
  assert.equal(h.button('save-profiles').disabled, true);
  await h.click('save-profiles'); await h.click('restore-defaults'); await h.click('restore-backup');
  assert.equal(h.post.length, 1);
  assert(!h.requests.some(r => r.route.startsWith('restore-')));
  h.release(); await saving; assert.equal(h.button('save-profiles').disabled, false);
});
test('failed save keeps draft and permits retry', async () => {
  const h = await setup(); h.edit(1280); h.rejectSave(); await h.click('save-profiles');
  assert.match(h.status.className, /error$/); assert.equal(h.button('save-profiles').disabled, false);
  assert.equal(h.dirty, true);
  h.allowSave(); await h.click('save-profiles'); assert.equal(h.post[1].body.profiles[0].presets[0].width, 1280);
});
test('server rejection of Unicode collision retains both profiles', async () => {
  const h = await setup(['Strasse']); await h.create('Straße'); h.rejectSave(); await h.click('save-profiles');
  assert.equal(h.post[0].body.profiles.length, 2); assert.match(h.status.className, /error$/);
  assert.equal(h.dirty, true);
  assert.match(h.nodes.get('#fnp-settings-profile').innerHTML, /Straße/);
  await h.click('delete-profile'); h.allowSave(); await h.click('save-profiles');
  assert.equal(h.post[1].body.profiles.length, 1);
});
for (const name of ['A'.repeat(27), 'A'.repeat(28), 'A'.repeat(32), '日本語'.repeat(10), '😀'.repeat(32)]) {
  test(`duplicate remains saveable: ${Array.from(name).length} codepoints (${name.slice(0, 3)})`, async () => {
    const h = await setup([name]); await h.click('duplicate-profile'); await h.click('save-profiles');
    assert.equal(h.post.length, 1); const profiles = h.post[0].body.profiles;
    assert(profiles[1].name.endsWith(' Copy')); assert(Array.from(profiles[1].name).length <= 32);
    assert(!/[\uD800-\uDBFF]$/.test(profiles[1].name));
  });
}
test('duplicate suffixes stay unique and bounded through two digits', async () => {
  const name = 'A'.repeat(32); const h = await setup([name]);
  for (let i = 0; i < 12; i++) { h.select(0); await h.click('duplicate-profile'); }
  await h.click('save-profiles'); const names = h.post[0].body.profiles.map(p => p.name);
  assert.equal(new Set(names).size, 13); assert(names.every(n => Array.from(n).length <= 32));
  assert(names.some(n => n.endsWith(' Copy 10')));
});
test('new profile length counts Unicode codepoints', async () => {
  const h = await setup(); await h.create('😀'.repeat(32)); await h.click('save-profiles');
  assert.equal(h.post[0].body.profiles.length, 2);
  await h.create('😀'.repeat(33)); assert.match(h.nodes.get('#fnp-settings-profile-dialog-error').textContent, /32/);
});
test('a normal save keeps the selected profile and does not restore stale history', async () => {
  const h = await setup(['One', 'Two']); h.select(1); h.edit(1280); h.hold();
  const saving = h.click('save-profiles'); await flush(); await h.click('clear-history');
  h.release(); await saving;
  assert.equal(h.nodes.get('#fnp-settings-profile').value, '1');
  assert.match(h.nodes.get('#fnp-settings-history').innerHTML, /No history/);
  assert.equal(h.dirty, false);
});

test('backup response cannot replace edits added during save', async () => {
  const h = await setup(); h.edit(1280); h.hold('backup'); const backup = h.click('backup');
  await flush(); h.edit(1536); await h.click('save-profiles');
  await h.create('AfterSave'); h.release(); await backup;
  assert.equal(h.dirty, true); await h.click('save-profiles');
  assert.equal(h.post[1].body.profiles[0].presets[0].width, 1536);
  assert.equal(h.post[1].body.profiles[1].name, 'AfterSave');
});
