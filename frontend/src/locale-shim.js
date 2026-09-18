// uPlot (a build-time chart dep) constructs `new Intl.NumberFormat(navigator.language)`
// at module load time. Some environments (headless Chromium under LANG=C.UTF-8, e.g.)
// report a malformed BCP-47 tag like "en-US@posix", which throws a RangeError and takes
// down the whole shell before it can mount (indah#76). Wrap the constructor so a bad
// locale falls back to en-US instead of crashing module evaluation. Must be imported
// before anything that imports uplot, since ES module subtrees evaluate in import order.
const OriginalNumberFormat = Intl.NumberFormat;
Intl.NumberFormat = function (locales, options) {
  try {
    return new OriginalNumberFormat(locales, options);
  } catch (e) {
    return new OriginalNumberFormat("en-US", options);
  }
};
Intl.NumberFormat.prototype = OriginalNumberFormat.prototype;
