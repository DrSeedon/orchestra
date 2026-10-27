// Offline evidence audit for this research snapshot; not a prompt wording regression test.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const dir = path.resolve('.orchestra/tasks/V-1102');
const root = process.cwd();
const reportPath = path.join(dir, 'report.md');
const report = fs.readFileSync(reportPath, 'utf8');
const sources = JSON.parse(fs.readFileSync(path.join(dir, 'sources.json'), 'utf8'));
const inputs = JSON.parse(fs.readFileSync(path.join(dir, 'local-inputs.json'), 'utf8'));
const errors = [];
const check = (condition, description) => { if (!condition) errors.push(description); };
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const normalize = text => text.replace(/\s+/g, ' ').trim();
const tableRows = report.split('\n').filter(line => /^\| \d{2}\. /.test(line));
const verdicts = {};
const localLinks = new Set();
const sourceLines = new Set();
const references = Object.fromEntries([...report.matchAll(/^\[([^\]]+)\]: (\S+)$/gm)].map(m => [m[1], m[2]]));
for (const input of inputs.files) {
  const file = path.resolve(root, input.path);
  check(fs.existsSync(file), `Input absent: ${input.path}`);
  if (fs.existsSync(file)) check(hash(fs.readFileSync(file)) === input.sha256, `Input changed: ${input.path}`);
}
const current = fs.readFileSync(path.join(dir, 'opencode-AGENTS.md'), 'utf8');
const before = fs.readFileSync(path.join(dir, 'opencode-AGENTS-before-rule.md'), 'utf8');
const added = fs.readFileSync(path.join(dir, 'opencode-AGENTS-rule-added.md'), 'utf8');
check(hash(current) === sources.upstream.sha256, 'Upstream snapshot hash differs');
check(current.trimEnd().split('\n').length === sources.upstream.lines, 'Upstream line count differs');
check(current.split('\n')[sources.rule.currentLine - 1] === sources.rule.text, 'Rule line differs from metadata');
check(!before.includes(sources.rule.text), 'Rule unexpectedly present in parent snapshot');
check(added.split('\n').includes(sources.rule.text), 'Rule absent from introduction snapshot');
check(sources.rule.blame.commitOid === sources.rule.introducedIn, 'Blame differs from introduction');
check(sources.pullRequest.mergeCommit === sources.rule.introducedIn, 'PR merge differs from introduction');
check(sources.rule.instructionPatch.split('\n').includes('+' + sources.rule.text), 'Commit patch does not introduce the rule');
for (const match of report.matchAll(/\]\[([^\]]+)\]/g)) check(Boolean(references[match[1]]), `Unresolved reference: ${match[1]}`);
for (const match of report.matchAll(/\]\(([^)]+)\)/g)) {
  const link = match[1];
  if (/^https?:/.test(link)) continue;
  const [file, anchor] = link.split('#');
  const target = path.resolve(dir, file);
  localLinks.add(link);
  check(target.startsWith(root + path.sep), `Local link leaves workspace: ${link}`);
  // audit.json is the output of this very check.
  if (target !== path.join(dir, 'audit.json')) check(fs.existsSync(target), `Local link absent: ${link}`);
  if (anchor?.startsWith('L') && fs.existsSync(target)) {
    const count = fs.readFileSync(target, 'utf8').trimEnd().split('\n').length;
    const end = Number(anchor.match(/L(\d+)$/)?.[1]);
    check(end > 0 && end <= count, `Invalid line anchor: ${link}`);
  }
}
for (const url of Object.values(references)) {
  check(/github\.com\/anomalyco\/opencode\/(?:blob|blame|commit)\/[a-f0-9]{40}(?:\/|$)/.test(url), `Unpinned primary reference: ${url}`);
}
let quotedAlreadyRows = 0;
for (let index = 0; index < tableRows.length; index++) {
  const row = tableRows[index];
  check(row.startsWith(`| ${String(index + 1).padStart(2, '0')}. `), `Nonsequential table row ${index + 1}`);
  const cells = row.split('|').slice(1, -1).map(x => x.trim());
  check(cells.length === 6, `Wrong column count in row ${index + 1}`);
  const verdict = cells[2]?.match(/\*\*(взять|уже есть|не брать)\*\*/)?.[1];
  check(Boolean(verdict), `Missing verdict in row ${index + 1}`);
  verdicts[verdict] = (verdicts[verdict] || 0) + 1;
  check(['высокая','средняя','низкая'].includes(cells[3]), `Invalid importance in row ${index + 1}`);
  check(cells[4] === 'не измерено', `Unsupported benefit in row ${index + 1}`);
  for (const match of cells[0].matchAll(/\]\[(O\d+)\]/g)) {
    const url = references[match[1]];
    const range = url?.match(/#L(\d+)(?:-L(\d+))?$/);
    check(Boolean(range), `No upstream line range in row ${index + 1}`);
    if (range) for (let line = +range[1]; line <= +(range[2] || range[1]); line++) sourceLines.add(line);
  }
  if (verdict === 'уже есть') {
    const quotes = [...cells[1].matchAll(/“([^”]+)”/g)].map(m => m[1]);
    check(quotes.length > 0, `No literal local quote in already-present row ${index + 1}`);
    const citedLines = [];
    for (const match of cells[1].matchAll(/\]\(([^)#]+)#L(\d+)(?:-L(\d+))?\)/g)) {
      const file = path.resolve(dir, match[1]);
      const start = +match[2];
      const label = cells[1].slice(0, match.index).match(/\[([^\]]+)$/)?.[1];
      const printedRange = label?.match(/:(\d+)[–-](\d+)$/);
      const end = +(match[3] || printedRange?.[2] || start);
      citedLines.push(fs.readFileSync(file, 'utf8').split('\n').slice(start - 1, end).join('\n'));
    }
    for (const quote of quotes) check(citedLines.some(text => normalize(text).includes(normalize(quote))), `Quote not in cited local lines for row ${index + 1}: ${quote}`);
    quotedAlreadyRows++;
  }
}
const meaningfulLines = [1,2,3,4,8,9,10,11,15,16,17,18,22,23,24,25,29,35,37,41,47,48,49,50,51,52,53,54,55,56,57,59,72,85,86,87,88,89,93,107,125,140,141,142,143,144,148,168,169,170,171,175,176,177,178,182,183,184,185,186,187,188,189,190,191];
for (const line of meaningfulLines) check(sourceLines.has(line), `Substantive upstream line not mapped: ${line}`);
check(tableRows.length === 69, 'Incomplete comparison table');
const secretPatterns = [
  ['private-key', /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/g],
  ['github-credential', /\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{40,})\b/g],
  ['provider-key', /\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}\b/g],
  ['telegram-bot-token', /\b\d{8,12}:[A-Za-z0-9_-]{30,}\b/g],
  ['aws-access-key', /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g],
  ['bearer-token', /\bBearer\s+[A-Za-z0-9._~+\/-]{25,}/g],
  ['embedded-url-credential', /https?:\/\/[^\s/@:]+:[^\s/@]{8,}@/g],
  ['assigned-secret', /\b(?:password|api_key|access_token|refresh_token|client_secret)\b\s*[:=]\s*["'][A-Za-z0-9_+\/-]{20,}["']/gi]
];
const secretFindings = [];
const scannedFiles = fs.readdirSync(dir).filter(name => !['audit.json','validation.log'].includes(name));
for (const name of scannedFiles) {
  const content = fs.readFileSync(path.join(dir, name), 'utf8');
  for (const [kind, regex] of secretPatterns) {
    regex.lastIndex = 0;
    let match;
    while ((match = regex.exec(content)) !== null) secretFindings.push({file:name,kind,line:content.slice(0,match.index).split('\n').length});
  }
}
check(secretFindings.length === 0, 'Secret-shaped material requires review; values suppressed');
const result = {
  checkedAt: new Date().toISOString(), offline: true, purpose: 'Research citation and artifact audit; no prompt behavior or prose regression tests',
  localInputsUnchanged: errors.every(x => !x.startsWith('Input')), localInputFiles: inputs.files.length,
  modules: inputs.files.filter(x => x.path.includes('/modules/')).length,
  upstreamSHA:sources.upstream.sha, upstreamLines:sources.upstream.lines, comparedRows:tableRows.length,
  substantiveRuleLinesCovered:meaningfulLines.length, verdicts, alreadyRowsWithVerifiedQuotes:quotedAlreadyRows,
  localLinkTargets:localLinks.size, primaryReferencesPinned:Object.keys(references).length,
  introductionVerified:true, sourceSecretShapeScan:{files:scannedFiles.length,patterns:secretPatterns.length,findings:secretFindings},
  unavailableChecks:['scripts/check_instruction_contract.py absent','scripts/run_tests.py absent','pytest test paths absent','app import unavailable'],
  errors, passed:errors.length === 0
};
fs.writeFileSync(path.join(dir, 'audit.json'), JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify(result, null, 2));
if (errors.length) process.exitCode = 1;
