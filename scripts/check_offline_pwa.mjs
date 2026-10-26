/* SPEC-050 — vérification CDP du mode hors-ligne (Chrome headless).
   Usage :
     1. lancer le serveur local sur http://127.0.0.1:8877 ;
     2. lancer Chrome headless avec --remote-debugging-port=9223 ;
     3. PHASE=online node scripts/check_offline_pwa.mjs   (amorce le cache)
     4. arrêter le serveur local ;
     5. PHASE=offline node scripts/check_offline_pwa.mjs  (vérifie le cache réel)

   La phase « offline » doit être exécutée serveur ARRÊTÉ : l'émulation réseau
   de CDP ne s'applique pas aux fetch du service worker lui-même, donc elle ne
   prouverait pas la bascule sur cache. Aucune donnée réelle n'est utilisée. */

const CDP_HTTP = process.env.CDP_HTTP || "http://127.0.0.1:9223";
const APP_URL = process.env.APP_URL || "http://127.0.0.1:8877/app";
const PHASE = process.env.PHASE === "offline" ? "offline" : "online";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function browserEndpoint() {
  const response = await fetch(`${CDP_HTTP}/json/version`);
  const body = await response.json();
  return body.webSocketDebuggerUrl;
}

function createClient(endpoint) {
  const socket = new WebSocket(endpoint);
  let nextId = 0;
  const pending = new Map();

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) reject(new Error(JSON.stringify(message.error)));
      else resolve(message.result);
    }
  });

  const ready = new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve);
    socket.addEventListener("error", reject);
  });

  function send(method, params = {}, sessionId) {
    const id = ++nextId;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }

  return { send, ready, close: () => socket.close() };
}

async function evaluate(client, sessionId, expression) {
  const result = await client.send(
    "Runtime.evaluate",
    { expression, awaitPromise: true, returnByValue: true },
    sessionId,
  );
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}

async function openApp(client) {
  const { targetId } = await client.send("Target.createTarget", { url: APP_URL });
  const { sessionId } = await client.send("Target.attachToTarget", { targetId, flatten: true });
  await client.send("Page.enable", {}, sessionId);
  await client.send("Runtime.enable", {}, sessionId);
  await sleep(3000);
  return sessionId;
}

async function main() {
  const client = createClient(await browserEndpoint());
  await client.ready;
  const sessionId = await openApp(client);

  if (PHASE === "online") {
    const registration = await evaluate(
      client,
      sessionId,
      `navigator.serviceWorker.ready.then((registration) => ({
        scope: registration.scope,
        state: registration.active && registration.active.state,
      }))`,
    );
    const status = await evaluate(
      client,
      sessionId,
      `document.getElementById("statusText")?.textContent || null`,
    );
    const cachedKeys = await evaluate(
      client,
      sessionId,
      `caches.keys().then((keys) => keys.sort())`,
    );
    console.log(JSON.stringify({ phase: PHASE, registration, status, cachedKeys }, null, 2));
  } else {
    const shell = await evaluate(
      client,
      sessionId,
      `({
        title: document.title,
        shell: Boolean(document.getElementById("view-today")),
        bannerVisible: !document.getElementById("offlineBanner")?.hidden,
        status: document.getElementById("statusText")?.textContent || null,
      })`,
    );
    const cachedApi = await evaluate(
      client,
      sessionId,
      `fetch("/api/career/dashboard").then((response) => ({
        status: response.status,
        fromCache: response.headers.get("X-Nage-Offline") === "1",
      }))`,
    );
    const unknownApi = await evaluate(
      client,
      sessionId,
      `fetch("/api/never-cached-" + Date.now()).then((response) => ({
        status: response.status,
        offline: response.headers.get("X-Nage-Offline") === "1",
      }))`,
    );
    console.log(JSON.stringify({ phase: PHASE, shell, cachedApi, unknownApi }, null, 2));
  }

  client.close();
}

main().catch((error) => {
  console.error("CDP_CHECK_FAILED:", error.message);
  process.exit(1);
});
