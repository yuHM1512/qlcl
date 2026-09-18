const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, 'templates/qc.html'), 'utf8');
const start = html.indexOf('        async function setPlanFinished(');
const end = html.indexOf('        async function syncQtcnPlans()', start);
const createHandler = new Function('fetch', 'showToast', html.slice(start, end) + ';return setPlanFinished;');

async function check(initial, result) {
    const checkbox = { checked: initial, disabled: false };
    const messages = [];
    const handler = createHandler(async (url, options) => {
        assert.equal(checkbox.disabled, true);
        assert.equal(url, '/api/prod-plan/123');
        assert.equal(options.method, 'PATCH');
        assert.deepEqual(JSON.parse(options.body), { is_finished: initial });
        if (result === 'network') throw new Error('Network unavailable');
        return { ok: result === 'success', json: async () => ({ detail: 'Forbidden' }) };
    }, (...args) => messages.push(args));
    await handler(123, checkbox);
    assert.equal(checkbox.disabled, false);
    assert.equal(checkbox.checked, result === 'success' ? initial : !initial);
    assert.equal(messages[0][1], result === 'success' ? 'success' : 'error');
}

(async () => {
    for (const initial of [true, false]) {
        for (const result of ['success', 'forbidden', 'network']) await check(initial, result);
    }
    console.log('Plan completion UI: finish, reopen, pending state and failure rollback passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
