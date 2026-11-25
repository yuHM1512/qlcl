const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, 'templates/qc_input_sp.html'), 'utf8');
const start = html.indexOf('    // "Th-12" -> ["Th", 12]');
const end = html.indexOf('    function vpRenderTable', start);
assert.ok(start > 0 && end > start, 'visual picker helpers not found');
const { vpSplitCode, vpSortedHotspots, vpBlockCode } = new Function(
  html.slice(start, end) + ';return { vpSplitCode, vpSortedHotspots, vpBlockCode };')();

// PDF codes, old Excel codes and codes with spaces all split into prefix + number.
assert.deepEqual(vpSplitCode('Th(1)-12'), ['Th(1)', 12]);
assert.deepEqual(vpSplitCode('TS1'), ['TS', 1]);
assert.deepEqual(vpSplitCode('L(1) - 10'), ['L(1)', 10]);
assert.deepEqual(vpSplitCode('Nh(1)-15'), ['Nh(1)', 15]);

// Table rows follow the PDF order (natural sort), not string order (Th-10 < Th-2).
const khoi = { hotspots: ['Th-10', 'Th-2', 'Th-1', 'Th-11', 'Th-3'].map((c, i) => ({ ma_vi_tri: c, chi_tiet_id: i })) };
assert.deepEqual(vpSortedHotspots(khoi).map(h => h.ma_vi_tri), ['Th-1', 'Th-2', 'Th-3', 'Th-10', 'Th-11']);
assert.equal(vpBlockCode(khoi), 'Th');
assert.equal(vpBlockCode({ hotspots: [] }), '');
console.log('Visual picker: code split, PDF row order and block header code passed.');
