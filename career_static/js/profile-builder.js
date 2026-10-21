/* Relecture du profil candidat, champ par champ.
 *
 * Ce fichier ne décide rien.  Il affiche les faits proposés par le serveur,
 * la source exacte de chaque fait (page, passage cité) et les décisions déjà
 * prises, puis il envoie au serveur une décision à la fois : approuver,
 * corriger, rejeter, mettre de côté ou supprimer.
 *
 * Le profil actif affiché ici ne contient que les faits approuvés ou
 * corrigés : un fait proposé, rejeté ou mis de côté ne justifie jamais une
 * candidature.
 */
(function (root) {
  "use strict";

  var BASE_PATH = "/api/career/profile-facts";
  var ACTIVE_PATH = "/api/career/profile-facts/active";
  var EXPORT_PATH = "/api/career/profile-facts/export";

  var STATUS_LABELS = {
    proposed: "À valider",
    approved: "Approuvé",
    rejected: "Rejeté",
    modified: "Corrigé",
    suspended: "Mis de côté",
  };

  var KIND_LABELS = {
    skill: "Compétence",
    experience: "Expérience",
    education: "Diplôme",
    language: "Langue",
    date: "Date",
    contact: "Coordonnée",
  };

  var SECTION_ID = "candidate-profile-builder";

  function request(path, options) {
    var settings = options || {};
    var init = {
      method: settings.method || "GET",
      headers: settings.body ? { "Content-Type": "application/json" } : {},
    };
    if (settings.body) init.body = settings.body;
    return fetch(path, init).then(function (response) {
      return response.json().catch(function () {
        return {};
      }).then(function (body) {
        if (!response.ok) {
          var detail = body && typeof body.detail === "string" ? body.detail : "Le profil candidat n’a pas pu être mis à jour.";
          var error = new Error(detail);
          error.status = response.status;
          throw error;
        }
        return body;
      });
    });
  }

  /* Les seuls faits qui peuvent justifier une candidature. */
  function activeFacts(facts) {
    var list = Array.isArray(facts) ? facts : [];
    return list.filter(function (fact) {
      return fact && (fact.status === "approved" || fact.status === "modified");
    });
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] || "Statut inconnu";
  }

  function kindLabel(kind) {
    return KIND_LABELS[kind] || kind;
  }

  function sourceLabel(fact) {
    var provenance = (fact && fact.provenance) || {};
    var page = provenance.page ? "page " + provenance.page : "page inconnue";
    var extraction = provenance.extraction === "ocr" ? " · lu par OCR" : "";
    return page + extraction;
  }

  function factUrl(factId, suffix) {
    return BASE_PATH + "/" + encodeURIComponent(factId) + suffix;
  }

  function loadFacts() {
    return request(BASE_PATH);
  }

  function loadActive() {
    return request(ACTIVE_PATH);
  }

  function exportProfile() {
    return request(EXPORT_PATH);
  }

  function approveFact(factId) {
    return request(factUrl(factId, "/approve"), { method: "POST" });
  }

  function rejectFact(factId) {
    return request(factUrl(factId, "/reject"), { method: "POST" });
  }

  function suspendFact(factId) {
    return request(factUrl(factId, "/suspend"), { method: "POST" });
  }

  function modifyFact(factId, value) {
    return request(factUrl(factId, "/modify"), {
      method: "POST",
      body: JSON.stringify({ value: value }),
    });
  }

  function deleteFact(factId) {
    return request(BASE_PATH + "/" + encodeURIComponent(factId), { method: "DELETE" });
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function renderFact(fact, onDecide, onDelete) {
    var item = element("li", "candidate-fact");
    item.setAttribute("data-fact-id", fact.fact_id);
    item.setAttribute("data-status", fact.status);

    var header = element("p", "candidate-fact-header");
    header.appendChild(element("strong", "candidate-fact-kind", kindLabel(fact.kind)));
    header.appendChild(document.createTextNode(" " + fact.label));
    item.appendChild(header);

    item.appendChild(element("p", "candidate-fact-value", fact.value));

    var source = element("p", "candidate-fact-source");
    source.appendChild(document.createTextNode(sourceLabel(fact)));
    var quote = (fact.provenance && fact.provenance.quote) || "";
    if (quote) {
      source.appendChild(element("span", "candidate-fact-quote", " « " + quote + " »"));
    }
    item.appendChild(source);

    var status = element("p", "candidate-fact-status", statusLabel(fact.status));
    item.appendChild(status);

    var actions = element("div", "candidate-fact-actions");
    actions.appendChild(button("Approuver", "primary-button", function () {
      onDecide(fact, "approve");
    }));
    actions.appendChild(button("Corriger", "secondary-button", function () {
      var value = root.prompt("Corrige la valeur de ce fait :", fact.value);
      if (value && value.trim() && value.trim() !== fact.value) {
        onDecide(fact, "modify", value.trim());
      }
    }));
    actions.appendChild(button("Rejeter", "secondary-button", function () {
      onDecide(fact, "reject");
    }));
    actions.appendChild(button("Mettre de côté", "quiet-button", function () {
      onDecide(fact, "suspend");
    }));
    actions.appendChild(button("Supprimer", "quiet-button", function () {
      onDelete(fact);
    }));
    item.appendChild(actions);
    return item;
  }

  function button(label, className, onClick) {
    var node = element("button", className, label);
    node.setAttribute("type", "button");
    node.addEventListener("click", onClick);
    return node;
  }

  function render(container, payload, handlers) {
    var facts = (payload && payload.facts) || [];
    container.textContent = "";

    var title = element("h3", "candidate-profile-title", "Profil candidat — relecture champ par champ");
    container.appendChild(title);

    var help = element(
      "p",
      "panel-help",
      "Chaque fait proposé garde sa source exacte (page et passage cité). Rien n’est approuvé automatiquement : les faits validés ici sont les seuls à pouvoir justifier une candidature."
    );
    container.appendChild(help);

    var counts = (payload && payload.counts) || {};
    var summary = element("p", "candidate-profile-counts");
    summary.setAttribute("aria-live", "polite");
    summary.textContent =
      "À valider : " + (counts.proposed || 0) +
      " · Approuvé : " + (counts.approved || 0) +
      " · Corrigé : " + (counts.modified || 0) +
      " · Rejeté : " + (counts.rejected || 0) +
      " · Mis de côté : " + (counts.suspended || 0);
    container.appendChild(summary);

    var list = element("ul", "candidate-fact-list");
    if (!facts.length) {
      container.appendChild(element("p", "empty-state", "Aucun fait proposé pour l’instant. Importe un document pour commencer."));
    } else {
      facts.forEach(function (fact) {
        list.appendChild(renderFact(fact, handlers.onDecide, handlers.onDelete));
      });
      container.appendChild(list);
    }

    var active = activeFacts(facts);
    var activeTitle = element("h4", "candidate-profile-active-title", "Profil actif");
    container.appendChild(activeTitle);
    var activeList = element("ul", "candidate-profile-active");
    if (!active.length) {
      container.appendChild(element("p", "empty-state", "Aucun fait approuvé : le profil actif est encore vide."));
    } else {
      active.forEach(function (fact) {
        var entry = element("li", "candidate-active-fact");
        entry.appendChild(element("strong", null, kindLabel(fact.kind)));
        entry.appendChild(document.createTextNode(" " + fact.value));
        activeList.appendChild(entry);
      });
      container.appendChild(activeList);
    }

    var exportButton = button("Exporter le profil (JSON)", "secondary-button", handlers.onExport);
    container.appendChild(exportButton);
    return container;
  }

  function ensureSection() {
    var existing = document.getElementById(SECTION_ID);
    if (existing) return existing;
    var host = document.getElementById("view-profile");
    if (!host) return null;
    var section = element("section", "candidate-profile");
    section.id = SECTION_ID;
    section.setAttribute("aria-labelledby", "candidate-profile-title");
    host.appendChild(section);
    return section;
  }

  function mount() {
    var section = ensureSection();
    if (!section) return null;

    function refresh() {
      return loadFacts().then(function (payload) {
        render(section, payload, {
          onDecide: function (fact, action, value) {
            var call;
            if (action === "approve") call = approveFact(fact.fact_id);
            else if (action === "reject") call = rejectFact(fact.fact_id);
            else if (action === "suspend") call = suspendFact(fact.fact_id);
            else call = modifyFact(fact.fact_id, value);
            return call.then(refresh);
          },
          onDelete: function (fact) {
            return deleteFact(fact.fact_id).then(refresh);
          },
          onExport: function () {
            return exportProfile().then(function (payload) {
              var blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
              var link = document.createElement("a");
              link.href = URL.createObjectURL(blob);
              link.download = "profil-candidat.json";
              link.click();
              URL.revokeObjectURL(link.href);
            });
          },
        });
        return payload;
      });
    }

    section.setAttribute("aria-busy", "true");
    return refresh()
      .catch(function (error) {
        section.appendChild(element("p", "empty-state", error.message));
        return null;
      })
      .then(function (payload) {
        section.removeAttribute("aria-busy");
        return payload;
      });
  }

  root.CareerProfileBuilder = {
    mount: mount,
    render: render,
    activeFacts: activeFacts,
    loadFacts: loadFacts,
    loadActive: loadActive,
    exportProfile: exportProfile,
    approveFact: approveFact,
    rejectFact: rejectFact,
    suspendFact: suspendFact,
    modifyFact: modifyFact,
    deleteFact: deleteFact,
  };

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", mount);
    } else {
      mount();
    }
  }
})(typeof window !== "undefined" ? window : globalThis);
