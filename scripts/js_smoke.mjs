#!/usr/bin/env node
/**
 * Garde-fous JavaScript de l'UI Career (job CI "javascript-tests").
 *
 * Aucune dépendance npm : uniquement les modules natifs de Node.
 * 1. Chaque fichier JS de l'UI doit être syntaxiquement valide.
 * 2. L'UI ne doit exposer aucune soumission automatique de candidature.
 * 3. Le contrat de pipeline (lecture seule) doit rester présent.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { spawnSync } from "node:child_process";

const root = new URL("..", import.meta.url).pathname;
const files = [];

function walk(directory) {
  for (const entry of readdirSync(directory)) {
    const absolute = join(directory, entry);
    if (statSync(absolute).isDirectory()) walk(absolute);
    else if (entry.endsWith(".js")) files.push(absolute);
  }
}

walk(join(root, "career_static"));
walk(join(root, "v5_static"));

const failures = [];

for (const file of files) {
  const result = spawnSync(process.execPath, ["--check", file], { encoding: "utf8" });
  if (result.status !== 0) {
    failures.push(`${relative(root, file)}: syntaxe invalide\n${result.stderr}`);
  }
}

const combined = files
  .map((file) => readFileSync(file, "utf8"))
  .join("\n");

const forbidden = [
  ["smtplib", /smtplib/],
  ["mailto:", /mailto:/i],
  ["envoi automatique", /automatic_submission["']?\s*[:=]\s*true/i],
  ["soumission de formulaire", /\.submit\s*\(\s*\)/],
  ["envoi de courriel", /sendMail|smtp\.send/i],
];

for (const [label, pattern] of forbidden) {
  if (pattern.test(combined)) failures.push(`motif interdit détecté : ${label}`);
}

const careerJs = readFileSync(join(root, "career_static", "career.js"), "utf8");
const indexHtml = readFileSync(join(root, "career_static", "index.html"), "utf8");
const contracts = [
  ["pipeline en lecture seule", careerJs.includes("/api/career/application-pipeline")],
  ["onglet candidatures", indexHtml.includes('id="tab-applications"')],
  ["aucun bouton d'envoi automatique", !/id="[^"]*(auto-apply|send-application)/i.test(indexHtml)],
];

for (const [label, present] of contracts) {
  if (!present) failures.push(`contrat UI manquant : ${label}`);
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log(`OK — ${files.length} fichiers JS valides, garde-fous anti-envoi présents.`);
