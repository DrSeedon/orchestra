"""Init script shared by the stand recorders."""

# Stand-only cosmetics: the English UI still formats some dates and money with a hard-coded
# 'ru-RU' locale (product i18n gap, see TODO.md) — map it to en-US in the recording browser.
EN_LOCALE = """(() => {
 const fix = l => (l === 'ru-RU' || l === 'ru') ? 'en-US' : l;
 const DTF = Intl.DateTimeFormat;
 Intl.DateTimeFormat = function (l, o) { return new DTF(fix(l), o) };
 Intl.DateTimeFormat.prototype = DTF.prototype; Intl.DateTimeFormat.supportedLocalesOf = DTF.supportedLocalesOf;
 for (const C of [Number, Date]) for (const m of ['toLocaleString', 'toLocaleDateString', 'toLocaleTimeString']) {
  const f = C.prototype[m]; if (f) C.prototype[m] = function (l, o) { return f.call(this, fix(l), o) } }
})();"""
