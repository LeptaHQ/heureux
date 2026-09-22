/* Exercise the production offset helpers without a browser or DOM dependency. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../static/study/js/annotations.js"), "utf8"
);

function productionFunctions(start, end) {
  const startIndex = source.indexOf("  function " + start + "(");
  const endIndex = source.indexOf("  function " + end + "(");
  assert(startIndex >= 0 && endIndex > startIndex);
  return source.slice(startIndex, endIndex);
}

function text(data) {
  return { nodeType: 3, data, parentElement: null };
}

function element(attrs = {}, children = [], tag = "p") {
  const node = {
    nodeType: 1, attrs, childNodes: children, parentElement: null,
    tag, dataset: {}, isConnected: true,
    matches(selector) {
      return selector.split(",").some((part) => {
        part = part.trim();
        const attributes = [...part.matchAll(/\[([^\]=]+)(?:=[^\]]+)?\]/g)];
        if (attributes.length) {
          return attributes.every((match) => Object.hasOwn(this.attrs, match[1]));
        }
        return part === this.tag;
      });
    },
    closest(selector) {
      for (let current = this; current; current = current.parentElement) {
        if (current.matches(selector)) return current;
      }
      return null;
    },
    querySelectorAll(selector) {
      const result = [];
      function visit(current) {
        for (const child of current.childNodes || []) {
          if (child.nodeType === 1 && child.matches(selector)) result.push(child);
          visit(child);
        }
      }
      visit(this);
      return result;
    },
    querySelector(selector) {
      return this.querySelectorAll(selector)[0] || null;
    },
    contains(child) {
      if (child === this) return true;
      return this.childNodes.some((node) =>
        node === child || (node.contains && node.contains(child))
      );
    },
    get textContent() {
      return this.childNodes.map((node) =>
        node.nodeType === 3 ? node.data : node.textContent
      ).join("");
    }
  };
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("data-")) {
      node.dataset[key.slice(5).replace(/-([a-z])/g, (_, letter) =>
        letter.toUpperCase()
      )] = value;
    }
  }
  for (const child of children) child.parentElement = node;
  return node;
}

function button() {
  const classes = new Set();
  return {
    hidden: false,
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name)
    },
    setAttribute() {}
  };
}

const first = text("Un même mot.");
const second = text("Un même mot.");
const last = text("Dernier 🇫🇷 exemple.");
const english = element(
  { "data-annotation-exclude": "", lang: "en" },
  [text("English repeats même and Un même mot. ".repeat(8)),
    element({}, [text("Nested English")], "em")]
);
const excludedRoot = element(
  { "data-annotation-exclude": "", "data-annotation-root": "",
    "data-annotation-source-key": "excluded" },
  [text("Never an anchor")]
);
const root = element(
  { "data-annotation-root": "", "data-annotation-source-key": "french",
    "data-annotation-legacy-source-keys": '["legacy-french"]' },
  [text("\n"), element({ lang: "fr" }, [first]), english, text("\n"),
    element({ lang: "fr" }, [second]), excludedRoot, text("\n"),
    element({ lang: "fr" }, [last])],
  "div"
);
const main = element({}, [root], "main");
let selection = null;
let savedNotes = 0;
const context = vm.createContext({
  Node: { ELEMENT_NODE: 1 },
  NodeFilter: { SHOW_TEXT: 4, FILTER_ACCEPT: 1, FILTER_REJECT: 2 },
  document: {
    createTreeWalker(root, _show, filter) {
      const nodes = [];
      function visit(node) {
        for (const child of node.childNodes || []) {
          if (child.nodeType === 3) {
            if (!filter || filter.acceptNode(child) === 1) nodes.push(child);
          } else visit(child);
        }
      }
      visit(root);
      return { nextNode: () => nodes.shift() || null };
    }
  },
  window: { getSelection: () => selection },
  main, currentSelection: null, highlights: [],
  noteButton: button(), highlightButton: button(), highlightLabel: {},
  createSelectionNote: () => { savedNotes += 1; return Promise.resolve({}); },
  showSelectionNoteSaved() {}
});

vm.runInContext(
  productionFunctions("selectionElement", "showToast") +
  productionFunctions("normalizedContext", "wrapSegment") +
  productionFunctions("highlightRoot", "applyHighlight") +
  source.slice(source.indexOf("  window.HeureuxNotes = {"), source.lastIndexOf("})();")),
  context
);

function select(range) {
  selection = { rangeCount: 1, isCollapsed: false, getRangeAt: () => range };
}

async function run() {
  const baseline = "\nUn même mot.\nUn même mot.\nDernier 🇫🇷 exemple.";
  assert.equal(context.annotationText(root), baseline);
  assert.equal(context.annotationText(main), baseline);
  assert.equal(context.annotationText(english), "");
  assert.equal(context.annotationText(excludedRoot), "");
  assert.equal(context.annotationText(element({}, [text("  intact\n \t")])), "  intact\n \t");

  const start = baseline.indexOf("même", baseline.indexOf("\nUn même mot.") + 2);
  const secondStart = baseline.lastIndexOf("même");
  assert(secondStart > start);
  const item = {
    id: 1, source_key: "french", quote: "même",
    start_offset: secondStart, end_offset: secondStart + 4,
    prefix: baseline.slice(0, secondStart),
    suffix: baseline.slice(secondStart + 4), revision: "saved"
  };
  assert.equal(context.bestOffsets(item, root).start, secondStart);
  assert.equal(context.bestOffsets(item, root).end, secondStart + 4);
  const segments = context.textSegments(root, secondStart, secondStart + 4, false);
  assert.equal(segments.length, 1);
  assert.equal(segments[0].node, second);
  assert.equal(segments[0].node.data.slice(segments[0].start, segments[0].end), "même");
  const allSegments = context.textSegments(root, 0, baseline.length, false);
  assert.equal(allSegments.map((segment) =>
    segment.node.data.slice(segment.start, segment.end)
  ).join(""), "Un même mot.Un même mot.Dernier 🇫🇷 exemple.");
  assert.equal(context.textSegments(main, 0, baseline.length, false).length, 0);
  assert.equal(context.textSegments(main, 0, baseline.length, true).length, 3);
  assert.equal(context.highlightRoot(item), root);
  assert.equal(context.highlightRoot({ ...item, source_key: "legacy-french" }), root);
  assert.equal(context.highlightRoot({ ...item, source_key: "excluded" }), null);

  const before = {
    selectNodeContents(node) { assert.equal(node, root); },
    setEnd(node, offset) { assert.equal(node, second); assert.equal(offset, 3); },
    cloneContents() {
      return element({}, [
        text("\nUn même mot."),
        element({ "data-annotation-exclude": "" }, [text(english.textContent)]),
        text("\nUn ")
      ]);
    }
  };
  const frenchRange = {
    startContainer: second, startOffset: 3,
    endContainer: second, endOffset: 7,
    commonAncestorContainer: second,
    cloneContents: () => element({}, [text("même")]),
    cloneRange: () => before
  };
  select(frenchRange);
  const captured = context.captureSelection();
  assert.equal(captured.root, root);
  assert.equal(captured.sourceKey, "french");
  assert.equal(captured.start, secondStart);
  assert.equal(captured.end, secondStart + 4);
  assert.equal(captured.quote, "même");
  assert.equal(captured.prefix, baseline.slice(0, secondStart));
  assert.equal(captured.suffix, baseline.slice(secondStart + 4));
  context.highlights = [item];
  context.refreshSelectionCoverage(captured);
  assert.equal(captured.fullyHighlighted, true);
  assert.equal(captured.highlight.start, secondStart);
  assert.equal(captured.highlight.prefix, captured.prefix);
  context.rememberSelection();
  assert(context.currentSelection);
  assert.equal(context.highlightButton.hidden, false);

  const englishText = english.childNodes[0];
  const englishRange = {
    startContainer: englishText, endContainer: englishText,
    commonAncestorContainer: englishText
  };
  select(englishRange);
  assert.equal(context.captureSelection(), null);
  assert.equal(context.window.HeureuxNotes.captureSelection(), null);
  assert.equal(context.currentSelection, null);
  assert.equal(context.noteButton.hidden, true);
  assert.equal(context.highlightButton.hidden, true);
  assert(context.noteButton.classList.contains("hidden"));
  assert.equal(selection.getRangeAt(0), englishRange);

  select({
    startContainer: first, endContainer: last, commonAncestorContainer: root,
    intersectsNode: (node) => node === english
  });
  assert.equal(context.captureSelection(), null);
  context.rememberSelection();
  assert.equal(context.currentSelection, null);
  select(frenchRange);
  context.rememberSelection();
  assert.equal(context.noteButton.hidden, false);
  assert.equal(context.highlightButton.hidden, false);
  assert.equal(context.highlightButton.classList.contains("hidden"), false);
  await assert.rejects(
    context.window.HeureuxNotes.saveSelectionNote("même", "English", true, null),
    /sélection n’est plus disponible/
  );
  assert.equal(savedNotes, 0);
  await context.window.HeureuxNotes.saveSelectionNote("même", "English", true);
  assert.equal(savedNotes, 1);

  const corrections = [1, 2, 3, 4].flatMap((number) => {
    const bank = JSON.parse(fs.readFileSync(path.join(
      __dirname, `../content/ee/tache_3/memoires/memoire_${number}.json`
    ), "utf8"));
    return bank.sections.flatMap((section) => section.groups.flatMap(
      (group) => group.questions.filter((question) => question.legacy_text)
    ));
  });
  assert.equal(corrections.length, 6);
  function savedAnchor(body, quote, start) {
    return {
      quote, start_offset: start, end_offset: start + quote.length,
      prefix: body.slice(Math.max(0, start - 160), start),
      suffix: body.slice(start + quote.length, start + quote.length + 160)
    };
  }
  function correctedElement(question) {
    return element(
      { "data-annotation-legacy-text": question.legacy_text },
      [text(question.text)]
    );
  }
  const opening = "\nAvant : même mot.\n";
  const closing = "\nAprès : même mot.\n";
  for (const question of corrections) {
    const correctedRoot = element({}, [
      text(opening), correctedElement(question),
      element({ "data-annotation-exclude": "" }, [text(question.english)]),
      text(closing)
    ]);
    const oldText = opening + question.legacy_text + closing;
    const newText = context.annotationText(correctedRoot);
    for (const occurrence of ["indexOf", "lastIndexOf"]) {
      const saved = savedAnchor(oldText, "même", oldText[occurrence]("même"));
      const projected = context.legacyCorrectionOffsets(saved, correctedRoot, newText);
      assert(projected, question.legacy_text);
      assert.equal(projected.start, newText[occurrence]("même"));
      assert.equal(context.bestOffsets(saved, correctedRoot).start, projected.start);
      const segments = context.textSegments(correctedRoot, projected.start, projected.end);
      assert.equal(segments.map((segment) =>
        segment.node.data.slice(segment.start, segment.end)
      ).join(""), "même");
    }
    const fresh = savedAnchor(newText, "même", newText.lastIndexOf("même"));
    assert.equal(context.legacyCorrectionOffsets(fresh, correctedRoot, newText), null);
    assert.equal(context.bestOffsets(fresh, correctedRoot).start, fresh.start_offset);
    const prefixLength = context.commonPrefixLength(question.legacy_text, question.text);
    const prefix = question.legacy_text.slice(0, Math.min(prefixLength, 5));
    const prefixAnchor = savedAnchor(oldText, prefix, opening.length);
    assert.equal(context.bestOffsets(prefixAnchor, correctedRoot).start, opening.length);
    const suffixLength = context.commonSuffixLength(question.legacy_text, question.text);
    if (suffixLength) {
      const suffix = question.legacy_text.slice(-Math.min(suffixLength, 5));
      const suffixAnchor = savedAnchor(
        oldText, suffix, opening.length + question.legacy_text.length - suffix.length
      );
      assert.equal(context.bestOffsets(suffixAnchor, correctedRoot).start,
        opening.length + question.text.length - suffix.length);
    }
    const changedAnchor = savedAnchor(oldText, question.legacy_text, opening.length);
    assert.equal(context.bestOffsets(changedAnchor, correctedRoot), null);
  }
  const combinedRoot = element({}, [
    text(opening),
    ...corrections.flatMap((question) => [correctedElement(question), text("\n")]),
    text(closing)
  ]);
  const originalCombined = opening +
    corrections.map((question) => question.legacy_text + "\n").join("") + closing;
  const combinedAnchor = savedAnchor(
    originalCombined, "même", originalCombined.lastIndexOf("même")
  );
  assert.equal(context.bestOffsets(combinedAnchor, combinedRoot).start,
    context.annotationText(combinedRoot).lastIndexOf("même"));
  console.log("Annotation exclusion offset, selection, recovery and stale-anchor checks passed.");
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
