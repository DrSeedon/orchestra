// Research provenance only: public documentation GETs; no accounts or inference.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';

const sources = [
  ['credits', 'https://developers.openai.com/api/docs/guides/chatgpt-api-credits.md'],
  ['sharing-current', 'https://help.openai.com/en/articles/10306912-sharing-feedback-evals-and-api-data-with-openai'],
  ['sharing-mirror', 'https://help-lb.openai.com/en/articles/10306912-sharing-feedback-evals-and-api-data-with-openai'],
  ['rate-limits', 'https://developers.openai.com/api/docs/guides/rate-limits.md'],
  ['spend-limits', 'https://developers.openai.com/api/docs/guides/spend-limits.md'],
  ['function-calling', 'https://developers.openai.com/api/docs/guides/function-calling.md'],
  ['pricing', 'https://developers.openai.com/api/docs/pricing.md'],
  ['prompt-caching', 'https://developers.openai.com/api/docs/guides/prompt-caching.md'],
  ['your-data', 'https://developers.openai.com/api/docs/guides/your-data.md'],
  ['changelog', 'https://developers.openai.com/api/docs/changelog.md'],
  ['sentinelx', 'https://openai.com/business/plugins/sentinelx/'],
  ['work-faq', 'https://learn.chatgpt.com/docs/enterprise/work-admin-faq.md'],
  ['chat-pricing', 'https://learn.chatgpt.com/docs/pricing.md'],
];
const sha256 = body => createHash('sha256').update(body).digest('hex');
const observations = sources.map(([id, url]) => {
  const observedAt = new Date().toISOString();
  try {
    const raw = execFileSync('curl', [
      '--fail', '--silent', '--show-error', '--location', '--max-time', '20',
      '--write-out', '\n__V1127_META__%{http_code}\t%{url_effective}', url,
    ], { encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
    const split = raw.lastIndexOf('\n__V1127_META__');
    if (split < 0) throw new Error('missing HTTP metadata');
    const body = raw.slice(0, split);
    const [status, effectiveUrl] = raw.slice(split + '\n__V1127_META__'.length).split('\t');
    const plain = body.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
      .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '').replace(/<[^>]+>/g, ' ')
      .replace(/&[^;\s]+;/g, ' ').replace(/\s+/g, ' ');
    return { id, url, effectiveUrl, observedAt, status: Number(status),
      bodySha256: sha256(body), bytes: Buffer.byteLength(body),
      markers: id.startsWith('sharing-') ? {
        build: plain.includes('Build'), launch: plain.includes('Launch'), grow: plain.includes('Grow'),
        oldTierLabels: /[Tt]iers?\s+[123]\s*[-–]\s*[25]/.test(plain),
        gpt61Sol: plain.includes('gpt-6.1-sol'),
        positiveBalance: plain.includes('positive account balance'),
        wholeRequest: plain.includes('entire request'),
      } : undefined };
  } catch (error) {
    // Do not publish command diagnostics or environment paths.
    const output = typeof error.stdout === 'string' ? error.stdout : '';
    const marker = output.lastIndexOf('\n__V1127_META__');
    const [status, effectiveUrl] = marker >= 0
      ? output.slice(marker + '\n__V1127_META__'.length).split('\t') : [];
    return { id, url, observedAt, status: status ? Number(status) : undefined,
      effectiveUrl, error: error.status ? `curl exit ${error.status}` : error.name };
  }
});
const paths = [
  'app/models.py', 'app/runtime_registry.py', 'app/backend_codex.py',
  'app/backend_harness.py', 'app/harness/llm.py', 'app/harness/loop.py',
  'app/backend_hub.py', 'app/claude_api_credits.py', 'app/db.py',
  'app/mcp_stdio.py', 'app/secret_mask.py',
];
const localSources = paths.map(path => ({ path, sha256: sha256(readFileSync(path)) }));
writeFileSync('.orchestra/tasks/V-1127/source-observations.json',
  JSON.stringify({ collectedAt: new Date().toISOString(), method: 'Unauthenticated public GET via curl; bodies hashed, not retained', observations, localSources }, null, 2) + '\n');
for (const row of observations) console.log(JSON.stringify({ id: row.id, status: row.status, error: row.error, markers: row.markers }));
