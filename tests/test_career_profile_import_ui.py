"""Browser helper regressions for explicit approval of imported CV fields."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_profile_import_fields_require_explicit_selection() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node absent: impossible d'exécuter le garde JavaScript")
    source = (ROOT / "career_static" / "career.js").read_text(encoding="utf-8")
    function = source.split("function createProfileImportField(", 1)[1].split(
        "\nfunction renderProfileImportDraft(", 1
    )[0]
    script = r'''
const assert = require("assert");
const created = [];
function make(tag, text, className) {
  return {tag, text, className, dataset:{}, children:[], append(...items){this.children.push(...items)}};
}
const document = {createElement(tag) {
  const element = {tagName:tag.toUpperCase(), children:[], append(...items){this.children.push(...items)}};
  created.push(element);
  return element;
}};
function Option(label, value) { this.label=label; this.value=value; }
const profileImportFieldLabels = {skills:"Compétences factuelles"};
const profileImportAppendableFields = new Set(["skills"]);
const profileImportLongFields = new Set(["skills"]);
FUNCTION
const row = createProfileImportField("skills", "Excel, valuation", ["Excel"]);
const checkbox = created.find(item => item.type === "checkbox");
assert.strictEqual(checkbox.checked, false, "import suggestions must not be pre-approved");
assert.strictEqual(row.dataset.field, "skills");
assert.strictEqual(row.children[0], checkbox);
'''.replace("FUNCTION", "function createProfileImportField(" + function)
    completed = subprocess.run(
        [node, "-e", script], capture_output=True, text=True, timeout=8
    )
    assert completed.returncode == 0, completed.stderr
