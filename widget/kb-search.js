/* Hybrid search in the browser, a step-by-step copy of app/lexical.py and app/search.py.
 *
 * The question is embedded by transformers.js with the same multilingual-e5-small int8 file the
 * server runs ("query: " prefix, mean pooling, normalization), the fragments' vectors, thresholds
 * and stop words come from kb-index.json (scripts/export_index.py). Nothing leaves the device.
 *
 * window.KbSearch = { loadEmbedder, create, stems }
 */
(function () {
  "use strict";

  var WORD = /[a-zа-я]+/g;

  function makeStems(lex) {
    var stop = {};
    lex.stopwords.forEach(function (w) { stop[w] = true; });
    return function stems(text) {
      var words = text.toLowerCase().replace(/ё/g, "е").match(WORD) || [];
      var out = [];
      words.forEach(function (w) {
        if (w.length < 3 || stop[w]) return;
        var s = w.slice(0, lex.stem);
        if (out.indexOf(s) < 0) out.push(s);
      });
      return out;
    };
  }

  function makeMatch(lex) {
    return function (a, b) {
      if (Math.min(a.length, b.length) < lex.min_match) return a === b;
      return a.indexOf(b) === 0 || b.indexOf(a) === 0;
    };
  }

  function dot(a, b) {
    var s = 0;
    for (var i = 0; i < a.length; i++) s += a[i] * b[i];
    return s;
  }

  /* index: kb-index.json; embed(text) -> Promise<Float32Array> of the "query: " vector */
  function create(index, embed) {
    var cfg = index.search;
    var stems = makeStems(index.lexical);
    var match = makeMatch(index.lexical);
    var chunks = index.chunks.slice();
    var extra = []; // the visitor's own text, kept in memory only

    function all() { return chunks.concat(extra); }
    function prepare(list) {
      list.forEach(function (c) { if (!c.stems) c.stems = stems(c.title + ". " + c.text); });
    }
    prepare(chunks);

    function idf(q, corpus) {
      var n = corpus.length, w = {};
      q.forEach(function (s) {
        var df = 0;
        corpus.forEach(function (doc) { if (doc.some(function (p) { return match(s, p); })) df++; });
        w[s] = Math.log((n + 1) / (df + 1)) + 1;
      });
      return w;
    }

    function overlap(q, passage, w) {
      var total = 0, hit = 0;
      q.forEach(function (s) {
        total += w[s];
        if (passage.some(function (p) { return match(s, p); })) hit += w[s];
      });
      return total ? hit / total : 0;
    }

    async function search(question) {
      var vec = await embed("query: " + question);
      var list = all();
      var cands = list.map(function (c) { return { chunk: c, dense: dot(c.vec, vec) }; });
      cands.sort(function (a, b) { return b.dense - a.dense; });
      cands = cands.slice(0, cfg.candidates);
      var q = stems(question);
      var w = idf(q, list.map(function (c) { return c.stems; }));
      cands.forEach(function (h) {
        h.lexical = overlap(q, h.chunk.stems, w);
        h.score = h.dense + cfg.lexical_weight * h.lexical;
      });
      cands.sort(function (a, b) { return b.score - a.score; });
      return cands.slice(0, cfg.top_k);
    }

    function confident(hit) {
      return !!hit && hit.dense >= cfg.min_dense && hit.lexical >= cfg.min_lexical;
    }

    function shownSources(hits) {
      if (!hits.length) return [];
      var out = [hits[0]];
      if (hits.length > 1 && hits[0].score - hits[1].score <= cfg.second_source_gap && hits[1].lexical > 0) out.push(hits[1]);
      return out;
    }

    /* the visitor's file, cut like app/kb.py parse_plain does */
    async function addText(name, text) {
      var title = name.replace(/\.[^.]+$/, "");
      var paras = splitLong(text.replace(/[ \t]+\n/g, "\n").replace(/([^\n])\n(?!\n)/g, "$1 ").trim());
      var list = [];
      for (var i = 0; i < paras.length; i++) {
        var vec = await embed("passage: " + title + ". " + paras[i]);
        list.push({ id: "u" + i, source: name, title: title, text: paras[i], vec: vec });
      }
      prepare(list);
      extra = list;
      return list.length;
    }

    function dropText() { extra = []; }

    return { search: search, confident: confident, shownSources: shownSources, addText: addText, dropText: dropText };
  }

  function splitLong(text) {
    var LIMIT = 900;
    if (text.length <= LIMIT) return [text];
    var parts = [], cur = "";
    text.split(/\n\n+|(?<=[.!?])\s+/).forEach(function (p) {
      if (cur && cur.length + p.length + 1 > LIMIT) { parts.push(cur.trim()); cur = ""; }
      cur += p + " ";
    });
    if (cur.trim()) parts.push(cur.trim());
    return parts;
  }

  /* opts: transformers (URL of transformers.min.js), modelPath (folder with
   * multilingual-e5-small/), wasmPaths, onProgress(loaded, total) */
  async function loadEmbedder(opts) {
    var tf = await import(opts.transformers);
    if (opts.modelPath) {
      tf.env.localModelPath = opts.modelPath;
      tf.env.allowLocalModels = true;
      tf.env.allowRemoteModels = false;
    }
    if (opts.wasmPaths) tf.env.backends.onnx.wasm.wasmPaths = opts.wasmPaths;
    var files = {};
    var extractor = await tf.pipeline("feature-extraction", opts.model || "multilingual-e5-small", {
      dtype: "q8",
      device: "wasm",
      progress_callback: function (p) {
        if (!opts.onProgress || p.status !== "progress" || !p.total) return;
        files[p.file] = [p.loaded, p.total];
        var loaded = 0, total = 0;
        Object.keys(files).forEach(function (k) { loaded += files[k][0]; total += files[k][1]; });
        opts.onProgress(loaded, total);
      },
    });
    return async function (text) {
      var out = await extractor(text, { pooling: "mean", normalize: true });
      return out.data;
    };
  }

  window.KbSearch = { loadEmbedder: loadEmbedder, create: create, makeStems: makeStems };
})();
