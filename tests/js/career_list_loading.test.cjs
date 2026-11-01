const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag, text, className) { this.tag = tag; this.text = text; this.className = className; this.attributes = {}; this.children = []; this.events = {}; }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { this.events[name] = callback; }
}

function helpers() {
  const source = fs.readFileSync(path.join(__dirname, '../../career_static/career.js'), 'utf8');
  const start = source.indexOf('function renderListSkeleton(');
  const end = source.indexOf('function reducedMotion(', start);
  assert.ok(start > 0 && end > start);
  const context = vm.createContext({ make: (...args) => new Element(...args), setMessage() {} });
  vm.runInContext(source.slice(start, end), context);
  return context;
}

test('successful request removes busy state and leaves rendered offers', async () => {
  const context = helpers(), target = new Element(), empty = { hidden: false };
  await context.withListLoading(target, empty, async () => {
    assert.equal(target.attributes['aria-busy'], 'true');
    assert.equal(target.children.length, 3);
    target.replaceChildren(new Element('article', 'Offer'));
  });
  assert.equal(target.attributes['aria-busy'], undefined);
  assert.equal(target.children[0].text, 'Offer');
});

test('failed request renders an alert and retry button, then recovers', async () => {
  const context = helpers(), target = new Element(), empty = { hidden: false };
  let calls = 0;
  const request = async () => {
    calls += 1;
    if (calls === 1) throw new Error('Synthetic network failure');
    target.replaceChildren(new Element('article', 'Recovered offer'));
  };
  await assert.rejects(context.withListLoading(target, empty, request), /Synthetic network/);
  assert.equal(target.attributes['aria-busy'], undefined);
  assert.equal(target.children[0].attributes.role, 'alert');
  assert.equal(target.children[1].text, 'Réessayer');
  target.children[1].events.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 2);
  assert.equal(target.children[0].text, 'Recovered offer');
  assert.equal(target.attributes['aria-busy'], undefined);
});
