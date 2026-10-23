/**
 * replay-cli recorder.js — manual capture for replay-cli.
 *
 * Paste this whole file into a page's DevTools console (or include it
 * via a script tag on a staging copy), then reproduce the bug.
 * When done, run:
 *
 *     copy(window.__replayCaptureJSON())
 *     window.__replayDownload()        // or downloads capture.json
 *
 * Save the JSON as capture.json and run:
 *
 *     python3 replay.py report capture.json
 *     python3 replay.py check  capture.json
 *
 * What it records, in the replay-cli capture format:
 *   - clicks / form fills as steps (selector + visible text)
 *   - console messages (log / warning / error)
 *   - fetch + XHR network calls with their status codes
 * Secrets are NOT stripped here — replay.py redacts Authorization,
 * Cookie and token/password values when it loads the capture. Still,
 * record on staging where you can, never with a real password.
 */
(function () {
  if (window.__replayCapture) {
    console.warn('[replay] already recording');
    return;
  }
  var start = performance.now();
  var t = function () { return Math.round((performance.now() - start) / 100) / 10; };
  var cap = {
    url: location.href,
    title: document.title,
    started_at: new Date().toISOString(),
    steps: [{ t: 0, type: 'goto', url: location.href }],
    console: [],
    network: [],
    logs: []
  };
  window.__replayCapture = cap;

  function selectorFor(el) {
    if (!el || el === document) return '';
    if (el.id) return '#' + el.id;
    var parts = [];
    var node = el;
    while (node && node.nodeType === 1 && parts.length < 4) {
      var part = node.tagName.toLowerCase();
      if (node.className && typeof node.className === 'string') {
        part += '.' + node.className.trim().split(/\s+/).join('.');
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(' > ');
  }

  document.addEventListener('click', function (e) {
    cap.steps.push({
      t: t(), type: 'click',
      selector: selectorFor(e.target),
      text: (e.target.innerText || '').slice(0, 80)
    });
  }, true);

  document.addEventListener('change', function (e) {
    if (e.target && (e.target.tagName === 'INPUT' ||
                     e.target.tagName === 'TEXTAREA' ||
                     e.target.tagName === 'SELECT')) {
      cap.steps.push({
        t: t(), type: 'fill',
        selector: selectorFor(e.target),
        value: e.target.type === 'password' ? '***' : e.target.value
      });
    }
  }, true);

  ['log', 'warn', 'error'].forEach(function (level) {
    var orig = console[level].bind(console);
    console[level] = function () {
      cap.console.push({
        t: t(),
        level: level === 'warn' ? 'warning' : level,
        text: Array.prototype.map.call(arguments, String).join(' ')
      });
      return orig.apply(null, arguments);
    };
  });

  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : input.url;
      var method = (init && init.method) ||
        (typeof input !== 'string' && input.method) || 'GET';
      var at = t();
      return origFetch.apply(this, arguments).then(function (resp) {
        cap.network.push({ t: at, method: method, url: url, status: resp.status });
        return resp;
      });
    };
  }

  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__replay = { method: method, url: url, t: t() };
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    var info = this.__replay;
    if (info) {
      this.addEventListener('load', function () {
        cap.network.push({ t: info.t, method: info.method, url: info.url, status: this.status });
      });
    }
    return origSend.apply(this, arguments);
  };

  window.__replayCaptureJSON = function () {
    return JSON.stringify(cap, null, 2);
  };
  window.__replayDownload = function () {
    var blob = new Blob([window.__replayCaptureJSON()], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'capture.json';
    a.click();
  };
  console.log('[replay] recording — reproduce the bug, then run __replayDownload()');
})();
