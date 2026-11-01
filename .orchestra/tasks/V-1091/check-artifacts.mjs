// Offline checks of this task's research artifacts; no upstream code execution.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
const base = '.orchestra/tasks/V-1091';
const report = fs.readFileSync(path.join(base, 'report.md'), 'utf8');
let localLinks = 0;
for (const match of report.matchAll(/\]\(([^)]+)\)/g)) {
  if (/^https?:/.test(match[1])) continue;
  const target = path.resolve(base, match[1].split('#')[0]);
  assert.ok(target.startsWith(path.resolve(base) + path.sep));
  assert.ok(fs.existsSync(target), `Missing report link: ${match[1]}`);
  localLinks++;
}
console.log(`PASS report local links=${localLinks}`);
let tableWidth = 0, tableRows = 0;
for (const line of report.split('\n')) {
  if (!line.startsWith('|')) { tableWidth = 0; continue; }
  const width = line.split('|').length;
  if (!tableWidth) tableWidth = width;
  assert.equal(width, tableWidth, `Table column mismatch: ${line}`);
  tableRows++;
}
console.log(`PASS Markdown table rows=${tableRows}`);
const tsv = fs.readFileSync(path.join(base, 'comparison.tsv'), 'utf8').trimEnd().split('\n');
const tsvWidth = tsv[0].split('\t').length;
for (const row of tsv) assert.equal(row.split('\t').length, tsvWidth);
console.log(`PASS comparison.tsv: ${tsv.length-1} data rows, ${tsvWidth} columns`);
const patterns = [
  ['private-key', /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/],
  ['openai-key', /\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}\b/],
  ['anthropic-key', /\bsk-ant-[A-Za-z0-9_-]{20,}\b/],
  ['github-token', /\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b/],
  ['telegram-token', /\b\d{6,12}:[A-Za-z0-9_-]{30,}\b/],
  ['jwt', /\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b/],
  ['aws-access-key', /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/],
  ['google-api-key', /\bAIza[A-Za-z0-9_-]{30,}\b/],
  ['credential-url', /https?:\/\/[^\s/@:]+:[^\s/@]+@/],
];
function walk(dir) {
  return fs.readdirSync(dir, {withFileTypes:true}).flatMap(e => {
    const full = path.join(dir, e.name);
    return e.isDirectory() ? walk(full) : [full];
  });
}
const artifacts = walk(base);
for (const file of artifacts) {
  const text = fs.readFileSync(file, 'utf8');
  for (const [name, pattern] of patterns) assert.ok(!pattern.test(text), `Secret-shape match ${name} in ${file}`);
}
console.log(`PASS secret-shape scan: ${artifacts.length} task files; 9 pattern classes; no matches`);
console.log('LIMIT secret-shape scan is finite; public SSH SIGNATURE is not a private key; no private env/logs read');
for (const line of fs.readFileSync(path.join(base, 'evidence/project-baseline.sha256'), 'utf8').trim().split('\n')) {
  const [, digest, name] = line.match(/^([a-f0-9]{64})\s+(.+)$/);
  assert.equal(crypto.createHash('sha256').update(fs.readFileSync(name)).digest('hex'), digest);
  console.log(`PASS unchanged protected file ${name}`);
}
console.log('PASS artifact checks complete; no source scripts, product code, model APIs or Python run');
