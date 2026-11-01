// Offline integrity checks written for this research task, not upstream code.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';

const base = '.orchestra/tasks/V-1091';
const read = p => fs.readFileSync(path.join(base, p));
const head = JSON.parse(read('evidence/github-head.json'));
const tree = JSON.parse(read('evidence/github-tree.json'));
const manifest = JSON.parse(read('evidence/source-manifest.json'));
const pinned = 'a2735a3eaf092eaaffb6dc17df25de33ef3bd048';
assert.equal(head.sha, pinned);
assert.equal(tree.sha, pinned);
assert.equal(tree.truncated, false);
const files = [
  ['README.md', 'README.md'],
  ['LICENSE', 'LICENSE'],
  ['skills/landing-page-design/SKILL.md', 'landing-page-design.SKILL.md'],
  ['skills/design-to-motion/SKILL.md', 'design-to-motion.SKILL.md'],
];
const hash = (alg, bytes) => crypto.createHash(alg).update(bytes).digest('hex');
const records = files.map(([upstream, local]) => {
  const bytes = read(`sources/github/${local}`);
  const entry = tree.tree.find(x => x.path === upstream);
  assert.ok(entry);
  assert.equal(bytes.length, entry.size);
  const blob = hash('sha1', Buffer.concat([Buffer.from(`blob ${bytes.length}\0`), bytes]));
  assert.equal(blob, entry.sha);
  const lines = bytes.toString('utf8').split('\n').length - (bytes.at(-1) === 10 ? 1 : 0);
  console.log(`PASS ${upstream} bytes=${bytes.length} lines=${lines} git_blob_sha1=${blob}`);
  return {path: upstream, local: `sources/github/${local}`, bytes: bytes.length,
    lines, git_blob_sha1: blob, sha256: hash('sha256', bytes),
    url: `https://github.com/elayadesign/ai-design-skills/blob/${pinned}/${upstream}`};
});
const landingEntries = tree.tree.filter(x => x.path.startsWith('skills/landing-page-design/'));
assert.deepEqual(landingEntries.map(x => x.path), ['skills/landing-page-design/SKILL.md']);
console.log('PASS recursive tree: landing has only SKILL.md; no bundled references/assets/scripts');
const official = [
  ['build-skills.md', 'https://learn.chatgpt.com/docs/build-skills.md'],
  ['agents-md.md', 'https://learn.chatgpt.com/docs/agent-configuration/agents-md.md'],
].map(([local, url]) => {
  const bytes = read(`sources/openai/${local}`);
  const expected = manifest.official.find(x => x.local === `sources/openai/${local}`);
  assert.ok(expected);
  assert.equal(hash('sha256', bytes), expected.sha256);
  console.log(`PASS official snapshot ${local} bytes=${bytes.length} sha256=${hash('sha256', bytes)}`);
  return {local: `sources/openai/${local}`, url, bytes: bytes.length, sha256: hash('sha256', bytes)};
});
const coreBytes = fs.statSync('AGENTS.md').size;
const coreLimit = 16 * 1024;
const landingBytes = read('sources/github/landing-page-design.SKILL.md').length;
console.log(`INFO core=${coreBytes} bytes; headroom below strict 16KiB=${coreLimit-1-coreBytes} bytes; hypothetical concatenation=${coreBytes+landingBytes} bytes`);
console.log('CONTEXT CLAUDE.md exists=' + fs.existsSync('CLAUDE.md') + '; not repaired in research task');
fs.writeFileSync(path.join(base, 'evidence/source-manifest.json'), JSON.stringify({
  pinned_commit: pinned, commit_date: head.commit.committer.date,
  tree: head.commit.tree.sha, github: records, official,
  official_snapshot_scope: 'Live official documentation fetched 2026-10-26 UTC; not a version-pinned product binary.',
}, null, 2) + '\n');
