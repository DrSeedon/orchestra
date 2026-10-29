// Deliberately small DOM double for offline JS concurrency tests. Real DOM
// behavior is covered by the same scenarios in the Playwright parametrization.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
    constructor(tag) {
        this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
        this.attributes = {}; this.listeners = {}; this.parentNode = null;
        this.className = ''; this._text = ''; this.disabled = false;
        this.classList = {
            add: value => { this.className += ` ${value}`; },
            remove: value => { this.className = this.className.split(' ').filter(c => c !== value).join(' '); },
        };
    }
    set textContent(text) { this.replaceChildren(); this._text = String(text); }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    get firstChild() { return this.children[0] || null; }
    appendChild(child) { child.remove(); child.parentNode = this; this.children.push(child); return child; }
    replaceChildren(...children) {
        this.children.forEach(child => { child.parentNode = null; }); this.children = []; this._text = '';
        children.forEach(child => this.appendChild(child));
    }
    remove() {
        if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this);
        this.parentNode = null;
    }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    click() { if (!this.disabled) this.listeners.click?.(); }
    matches(selector) {
        if (selector.startsWith('#')) return this.id === selector.slice(1);
        if (selector.startsWith('.')) return this.className.split(' ').includes(selector.slice(1));
        const attribute = /^\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(selector);
        if (attribute) {
            const [, name, value] = attribute;
            const stored = name.startsWith('data-')
                ? this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())]
                : this.attributes[name];
            return stored !== undefined && (value === undefined || stored === value);
        }
        return this.tagName.toLowerCase() === selector;
    }
    querySelectorAll(selector) {
        return this.children.flatMap(child => [ ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}
const body = new Element('body');
for (const [tag, id] of [['div','queued-messages'], ['div','chat'], ['textarea','chat-input'], ['button','send-btn'], ['button','send-after-turn-btn']]) {
    const element = new Element(tag); element.id = id; element.value = ''; body.appendChild(element);
}
global.document = {body, addEventListener() {}, createElement: tag => new Element(tag), querySelector: selector => body.querySelector(selector)};
global.window = global;
const root = path.resolve(__dirname, '..');
for (const filename of ['tests/queued_messages_v1134_setup.js', 'app/static/js/chat.js', 'tests/queued_messages_v1134_scenarios.js']) {
    vm.runInThisContext(fs.readFileSync(path.join(root, filename), 'utf8'), {filename});
}
runQueueScenario(process.argv[2]).then(name => console.log(`PASS ${name}`)).catch(error => { console.error(error); process.exitCode = 1; });
