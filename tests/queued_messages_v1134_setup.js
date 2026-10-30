// Shared browser/Node environment. Only API and unrelated chat subsystems are
// substituted; tests load and execute the complete production chat.js.
var selectedAgent = 'synthetic-agent';
var currentScope = '/synthetic-scope';
var localMessages = new Set();
var UI_DEBOUNCE_MS = 60000;
var drafts = {};
var LivePacer = class { reset() {} };
var requests = [];
var errors = [];
var $ = selector => document.querySelector(selector);
var T = (key, values = {}) => Object.entries(values).reduce(
    (text, [name, value]) => text.replaceAll(`{${name}}`, value), key,
);
var api = (url, options = {}) => new Promise((resolve, reject) => {
    requests.push({url, options, resolve, reject});
});
function clearPastePreview() {}
function liveResetActivity() {}
function cancelAnimationFrame() {}
function showImagePreview() {}
