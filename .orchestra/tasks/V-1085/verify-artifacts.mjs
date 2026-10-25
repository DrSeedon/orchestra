// Offline validation of this research bundle. Does not execute any API examples.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const inventory = JSON.parse(fs.readFileSync(path.join(dir, 'sources/api-inventory.json'), 'utf8'));
assert.equal(inventory.entries.length, 592);
assert(inventory.entries.every(e => e.status === 200 && !e.error));
assert(inventory.entries.every(e => e.method && e.endpoint && /^[a-f0-9]{64}$/.test(e.sha256)));
assert(inventory.entries.every(e => e.url.startsWith('https://elevenlabs.io/docs/')));
const routes = new Set(inventory.entries.map(e => e.method + ' ' + e.endpoint.replace(/^https?:\/\/api\.elevenlabs\.io/, '')));
assert.equal(routes.size, 400);
const linkCheck = JSON.parse(fs.readFileSync(path.join(dir, 'sources/report-link-check.json'), 'utf8'));
assert.equal(linkCheck.results.length, 94);
assert(linkCheck.results.every(e => e.status === 200));

for (const name of ['report.md', 'recommendations.md', 'endpoint-catalog.md', 'verification.md']) {
  const text = fs.readFileSync(path.join(dir, name), 'utf8');
  assert.equal((text.match(/^```/gm) ?? []).length % 2, 0, `${name}: unclosed code block`);
  const defs = new Set([...text.matchAll(/^\[([^\]]+)\]: \S+$/gm)].map(m => m[1]));
  for (const m of text.matchAll(/\[[^\]\n]+\]\[([^\]\n]+)\]/g)) {
    assert(defs.has(m[1]), `${name}: undefined reference ${m[1]}`);
  }
  for (const m of text.matchAll(/\[[^\]\n]+\]\(([^)\n]+)\)/g)) {
    if (!/^https?:|^#/.test(m[1])) assert(fs.existsSync(path.join(dir, m[1])), `${name}: missing local target ${m[1]}`);
  }
  let tableColumns = null;
  for (const line of text.split('\n')) {
    if (!line.startsWith('|')) { tableColumns = null; continue; }
    const columns = line.split(/(?<!\\)\|/).length;
    if (tableColumns === null) tableColumns = columns;
    assert.equal(columns, tableColumns, `${name}: malformed table row ${line.slice(0, 100)}`);
  }
  assert(!/\b(?:sk|sk_live|sk_test|ghp|github_pat)-[A-Za-z0-9_]{16,}\b/.test(text), `${name}: secret-shaped token`);
  assert(!/-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----/.test(text), `${name}: private key`);
}

const report = fs.readFileSync(path.join(dir, 'report.md'), 'utf8');
for (const match of report.matchAll(/--data '([^']+)'/g)) JSON.parse(match[1]);
const headers = [...report.matchAll(/(?:xi-api-key: |"xi-api-key": ")([^'"\n]+)/g)].map(m => m[1]);
assert(headers.length > 0 && headers.every(value => value === '<API_KEY>'));
assert(report.includes('XuEV9VY3VUASYgJVNBh0'));
assert(report.includes('root-reported private account check 25 Oct 2026'));
assert(report.includes('ElevenLabs SDK не устанавливался'));
console.log('PASS: 592 public schema pages, 400 routes, 94 checked official source links; Markdown links/tables/fences, curl JSON and credential placeholders validated offline. No API examples executed.');
