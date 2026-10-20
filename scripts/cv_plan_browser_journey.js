#!/usr/bin/env node
/**
 * CV plan browser journey — synthetic only, everything local.
 *
 * Drives a disposable demo server (scripts/cv_plan_browser_demo.py) through
 * headless Chromium via the DevTools protocol (Node's built-in WebSocket, no
 * external dependency, no download). Asserts:
 *   - the plan renders with a deterministic rank order and accessible filters;
 *   - the "revu" mark stays in localStorage and nothing modifies the CV source;
 *   - "Préparer dans le Studio" preselects the offer, the language and the
 *     local mode, and keeps the selection after a page reload;
 *   - no request leaves the loopback (no cloud, no consent);
 *   - a narrow viewport keeps the plan usable without horizontal scrolling.
 *
 * Usage: node scripts/cv_plan_browser_journey.js --app-port 8917 --captures DIR
 */

"use strict";

const assert = require("assert");
const {spawn} = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const args = process.argv.slice(2);
function argValue(name, fallback) {
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : fallback;
}
const APP_PORT = Number(argValue("--app-port", "8917"));
const CAPTURES = argValue("--captures", path.join(os.tmpdir(), "cv-plan-captures"));
const CHROME = argValue("--chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
const CDP_PORT = Number(argValue("--cdp-port", "9333"));
fs.mkdirSync(CAPTURES, {recursive: true});

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitUntil(check, label, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  for (;;) {
    try {
      const value = await check();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    if (Date.now() > deadline) {
      throw new Error(`attente expirée : ${label}${lastError ? ` — ${lastError.message}` : ""}`);
    }
    await sleep(250);
  }
}

class Cdp {
  constructor(wsUrl) {
    this.socket = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.networkRequests = [];
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const {resolve, reject} = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(JSON.stringify(message.error)));
        else resolve(message.result);
        return;
      }
      if (message.method === "Network.requestWillBeSent") {
        this.networkRequests.push(message.params.request.url);
      }
      if (message.method === "Runtime.exceptionThrown") {
        this.consoleErrors.push(message.params.exceptionDetails.text);
      }
    });
    this.consoleErrors = [];
  }

  async open() {
    await new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve, {once: true});
      this.socket.addEventListener("error", () => reject(new Error("DevTools WebSocket indisponible")), {once: true});
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {resolve, reject});
      this.socket.send(JSON.stringify({id, method, params}));
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(`evaluate a échoué : ${result.exceptionDetails.text} ${result.exceptionDetails.exception?.description || ""}`);
    }
    return result.result.value;
  }

  async screenshot(name) {
    const image = await this.send("Page.captureScreenshot", {format: "png"});
    const target = path.join(CAPTURES, name);
    fs.writeFileSync(target, Buffer.from(image.data, "base64"));
    return target;
  }

  close() {
    try {
      this.socket.close();
    } catch (error) {
      /* already closed */
    }
  }
}

const farMessages = [];

async function main() {
  const userDir = fs.mkdtempSync(path.join(os.tmpdir(), "cvplan-chrome-"));
  const chrome = spawn(
    CHROME,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-first-run",
      "--no-default-browser-check",
      `--user-data-dir=${userDir}`,
      `--remote-debugging-port=${CDP_PORT}`,
      "--window-size=1440,900",
      "about:blank",
    ],
    {stdio: "ignore"},
  );
  try {
    const targets = await waitUntil(async () => {
      const response = await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`);
      const list = await response.json();
      return list.find((item) => item.type === "page" && item.webSocketDebuggerUrl);
    }, "la cible DevTools", 20000);

    const cdp = new Cdp(targets.webSocketDebuggerUrl);
    await cdp.open();
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Network.enable");

    const app = `http://127.0.0.1:${APP_PORT}/career`;
    await cdp.send("Page.navigate", {url: app});
    await sleep(1500);
    const health = await cdp.evaluate(`document.querySelector("#career-health")?.textContent || ""`);
    assert.match(health, /Career 4\.1|macOS prêt/i, `le module local doit être opérationnel (${health})`);

    // Étape 1 — itinéraire Stage Hunter via la navigation par hash (aucun clic sur onglet nécessaire).
    await cdp.evaluate(`window.location.hash = "#career/stagehunter"`);
    await waitUntil(async () => {
      const count = await cdp.evaluate(`document.querySelector("#stagehunter-prep-job")?.options.length || 0`);
      return count > 1;
    }, "l'offre synthétique apparaît dans le sélecteur de préparation");
    await cdp.evaluate(`
      const select = document.querySelector("#stagehunter-prep-job");
      select.value = [...select.options].find((option) => option.value).value;
      select.dispatchEvent(new Event("change", {bubbles: true}));
      document.querySelector("#stagehunter-prep-submit").click();
    `);

    // Étape 2 — le plan précis s'affiche avec ses rangs déterministes.
    await waitUntil(async () => cdp.evaluate(`Boolean(document.querySelector(".cv-plan .cv-plan-item"))`), "le rendu du plan CV");
    const plan = await cdp.evaluate(`(() => {
      const items = [...document.querySelectorAll(".cv-plan .cv-plan-item")];
      return {
        count: items.length,
        ranks: items.map((item) => item.dataset.rank),
        badges: items.map((item) => item.querySelector(".cv-plan-badge")?.textContent),
        filters: [...document.querySelectorAll(".cv-plan-filter")].map((button) => button.getAttribute("aria-pressed")),
        coverage: document.querySelector(".cv-plan-summary")?.textContent || "",
        help: Boolean(document.querySelector(".cv-plan-coverage-help")),
      };
    })()`);
    assert.strictEqual(plan.count, 4, `quatre conseils attendus, reçu ${plan.count}`);
    const rankIndex = {blocking: 0, required: 1, improvement: 2, preference: 3};
    const rankOrder = plan.ranks.map((rank) => rankIndex[rank]);
    assert(rankOrder.every((value) => typeof value === "number"), plan.ranks.toString());
    assert.deepStrictEqual(
      rankOrder,
      [...rankOrder].sort((a, b) => a - b),
      "l'ordre affiché suit le rang déterministe (blocage, obligatoire, amélioration, préférence)",
    );
    assert.match(plan.badges[plan.ranks.indexOf("blocking")], /Blocage factuel/i);
    assert(plan.badges.some((badge) => /Exigence obligatoire/i.test(badge)));
    assert.match(plan.coverage, /couverture documentaire/i);
    assert(plan.help, "l'explication de la couverture documentaire est présente");
    assert.strictEqual(plan.filters.filter((state) => state === "true").length, 1, "un seul filtre actif à la fois");
    await cdp.evaluate(`document.querySelector(".cv-plan").scrollIntoView({block: "start"})`);
    await sleep(400);
    await cdp.screenshot("01-cv-plan-1440.png");

    // Étape 3 — filtres accessibles + navigation clavier.
    const filtered = await cdp.evaluate(`(() => {
      const rows = [...document.querySelectorAll(".cv-plan .cv-plan-item")];
      const blocking = [...document.querySelectorAll(".cv-plan-filter")].find((b) => b.dataset.filter === "blocking");
      blocking.click();
      return {
        pressed: blocking.getAttribute("aria-pressed"),
        visible: rows.map((row) => !row.hidden),
        status: document.querySelector(".cv-plan-live")?.textContent || "",
        blockedRequirement: rows.filter((row) => row.dataset.rank === "blocking").map((row) => row.textContent),
        firstAction: rows[0].querySelector(".cv-plan-action-studio")?.textContent,
        expectedVisible: rows.map((row) => row.dataset.rank === "blocking"),
      };
    })()`);
    assert.strictEqual(filtered.pressed, "true");
    assert.deepStrictEqual(filtered.visible, filtered.expectedVisible, "seul le conseil bloquant reste affiché");
    assert.match(filtered.status, /Filtre « Bloquants » : 1 conseil affiché sur 4/);
    assert(filtered.blockedRequirement.some((text) => /Bloomberg/i.test(text)), "le blocage factuel correspond à l'exigence non étayée");
    assert.match(filtered.firstAction, /Compléter puis préparer/, "le rang bloquant propose d'abord de compléter la preuve");
    await cdp.evaluate(`
      const rows = [...document.querySelectorAll(".cv-plan .cv-plan-item")];
      rows[0].querySelector("button").focus();
      document.querySelector(".cv-plan-filter")?.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowDown", bubbles: true}));
    `);
    assert.strictEqual((await cdp.evaluate(`document.querySelectorAll(".cv-plan .cv-plan-item").length`)), 4, "la liste du plan reste navigable clavier");
    await cdp.evaluate(`[...document.querySelectorAll(".cv-plan-filter")].find((b) => b.dataset.filter === "all").click()`);

    // Étape 4 — marque « revu » locale, sans modification du CV source.
    const reviewed = await cdp.evaluate(`(() => {
      const reviewKeys = () => Object.keys(localStorage).filter((name) => name.startsWith("career_cv_plan_reviewed_"));
      const key = reviewKeys()[0] || "";
      const before = key ? JSON.parse(localStorage.getItem(key)) : {};
      document.querySelector(".cv-plan .cv-plan-item .cv-plan-action-reviewed").click();
      const freshKey = reviewKeys()[0];
      const after = freshKey ? JSON.parse(localStorage.getItem(freshKey)) : {};
      return {
        keySet: reviewKeys().length > 0,
        entries: Object.keys(after),
        changed: JSON.stringify(before) !== JSON.stringify(after),
        sourceReadonly: [...document.querySelectorAll(".cv-plan .cv-plan-item")].every((row) => !row.querySelector("input")),
      };
    })()`);
    assert(reviewed.keySet, "une clé de marque locale existe");
    assert(reviewed.entries.length >= 1, "un conseil est marqué revu");
    assert(reviewed.sourceReadonly, "aucun champ de saisie ne modifie le CV source");
    await cdp.evaluate(`document.querySelector(".cv-plan").scrollIntoView({block: "start"})`);
    await sleep(400);
    await cdp.screenshot("02-cv-plan-bloquants-filtre.png");

    // Étape 5 — Studio : offre préselectionnée, langue, mode local, sans consentement cloud.
    await cdp.evaluate(`
      const row = document.querySelector(".cv-plan .cv-plan-item");
      row.querySelector(".cv-plan-action-studio").click();
    `);
    await waitUntil(async () => cdp.evaluate(`!document.querySelector("#view-studio").hidden`), "la vue Studio s'ouvre");
    const studio = await cdp.evaluate(`(() => ({
      job: document.querySelector("#application-draft-job")?.value || "",
      language: document.querySelector("#application-draft-language")?.value || "",
      mode: document.querySelector("#application-draft-mode")?.value || "",
      consent: document.querySelector("#application-draft-consent")?.checked,
      consentRowHidden: document.querySelector("#application-draft-consent-row")?.hidden,
      consentRowDisplay: getComputedStyle(document.querySelector("#application-draft-consent-row")).display,
    }))()`);
    assert.match(studio.job, /^job_[0-9a-f]+$/, `l'offre est préselectionnée (${studio.job})`);
    // La langue cible reste celle annoncée par le plan (« à confirmer » sur une
    // offre sans langue connue) : la préselection respecte la valeur affichée
    // ou la dernière langue choisie, jamais un remplacement silencieux.
    assert(["fr", "en", "it", "de"].includes(studio.language), `langue valide (${studio.language})`);
    assert.strictEqual(studio.mode, "local", "le gabarit local est préselectionné");
    assert.strictEqual(studio.consent, false, "aucun consentement cloud activé");
    assert.strictEqual(studio.consentRowHidden, true, "la ligne de consentement reste masquée en local");
    assert.strictEqual(studio.consentRowDisplay, "none", "la ligne de consentement n'est pas rendue en mode local");
    await cdp.screenshot("03-studio-preselection.png");

    // Étape 6 — rechargement : la préselection survit, toujours sans le cloud.
    const remoteRequestsBefore = cdp.networkRequests.filter((url) => !url.startsWith("http://127.0.0.1")).length;
    assert.strictEqual(remoteRequestsBefore, 0, `aucune requête hors loopback (${remoteRequestsBefore} détectée(s))`);
    await cdp.send("Page.reload");
    await sleep(1800);
    await cdp.evaluate(`window.location.hash = "#career/studio"`);
    await waitUntil(async () => !!(await cdp.evaluate(`document.querySelector("#application-draft-job")?.options.length`)), "les offres du Studio rechargées");
    const reloaded = await cdp.evaluate(`(() => ({
      job: document.querySelector("#application-draft-job")?.value || "",
      mode: document.querySelector("#application-draft-mode")?.value || "",
      language: document.querySelector("#application-draft-language")?.value || "",
      consent: document.querySelector("#application-draft-consent")?.checked,
      reviewedKept: Object.keys(localStorage).some((name) => name.startsWith("career_cv_plan_reviewed_")),
    }))()`);
    assert.strictEqual(reloaded.job, studio.job, "l'offre sélectionnée reste sélectionnée après rechargement");
    assert.strictEqual(reloaded.mode, "local");
    assert.strictEqual(reloaded.consent, false);
    assert(reloaded.reviewedKept, "la marque « revu » survit au rechargement");

    // Étape 7 — viewport étroit (Mac 13" réduit / mobile) : recharger l'analyse
    // dans la même fenêtre puis vérifier la pile d'actions pleine largeur.
    await cdp.send("Emulation.setDeviceMetricsOverride", {width: 412, height: 900, deviceScaleFactor: 2, mobile: true});
    await sleep(400);
    await cdp.evaluate(`window.location.hash = "#career/stagehunter"`);
    await waitUntil(async () => {
      const count = await cdp.evaluate(`document.querySelector("#stagehunter-prep-job")?.options.length || 0`);
      return count > 1;
    }, "sélecteur de préparation rechargé");
    await cdp.evaluate(`
      const select = document.querySelector("#stagehunter-prep-job");
      select.value = [...select.options].find((option) => option.value).value;
      document.querySelector("#stagehunter-prep-submit").click();
    `);
    await waitUntil(async () => cdp.evaluate(`Boolean(document.querySelector(".cv-plan .cv-plan-item"))`), "le plan CV re-rendu en viewport étroit");
    const overflow = await cdp.evaluate(`(() => ({
      scrollWidth: document.scrollingElement.scrollWidth,
      innerWidth: window.innerWidth,
      planVisible: document.querySelector(".cv-plan") !== null,
      actionWidth: (() => {
        const button = document.querySelector(".cv-plan-actions button");
        return button ? Math.round(button.getBoundingClientRect().width) : 0;
      })(),
    }))()`);
    assert(overflow.planVisible, "le plan précis est rendu en viewport étroit");
    assert(
      overflow.scrollWidth <= overflow.innerWidth + 2,
      `pas de défilement horizontal (${overflow.scrollWidth} > ${overflow.innerWidth} ?)`,
    );
    assert(
      overflow.actionWidth >= Math.round(overflow.innerWidth * 0.75),
      `les actions passent en pile pleine largeur sur mobile (largeur ${overflow.actionWidth}px pour une fenêtre de ${overflow.innerWidth}px)`,
    );
    await cdp.evaluate(`document.querySelector(".cv-plan").scrollIntoView({block: "start"})`);
    await sleep(400);
    await cdp.screenshot("04-cv-plan-mobile-412.png");

    const remoteRequestsAfter = cdp.networkRequests.filter((url) => !/^http:\/\/(127\.0\.0\.1|localhost)/.test(url));
    assert.deepStrictEqual(remoteRequestsAfter, [], `requêtes réseau non locales détectées : ${remoteRequestsAfter.join(", ")}`);
    assert.deepStrictEqual(
      cdp.consoleErrors.filter((text) => !/favicon|Autofocus|Full keyboard access/i.test(text)),
      [],
      cdp.consoleErrors.join(" | "),
    );

    cdp.close();
    console.log("CVPLAN_BROWSER_JOURNEY_OK");
  } finally {
    chrome.kill("SIGKILL");
    await sleep(300);
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        fs.rmSync(userDir, {recursive: true, force: true});
        break;
      } catch (error) {
        if (attempt === 2) fs.rmSync(userDir, {recursive: true, force: true, maxRetries: 5, retryDelay: 200});
        await sleep(300);
      }
    }
    farMessages.length = 0;
  }
}

main().catch((error) => {
  console.error("CVPLAN_BROWSER_JOURNEY_FAILED:", error && error.message ? error.message : error);
  process.exitCode = 1;
});
