/* SPEC-013 — graphe de dépendances interactif, 100 % local.
 *
 * Aucun appel externe : toutes les requêtes sont same-origin.  Le graphe est
 * dessiné en SVG sans bibliothèque, avec zoom molette, déplacement, filtres
 * par type et mise en évidence du chemin critique après une analyse d'impact.
 */
(function () {
  "use strict";

  const API = "/dependencies";
  const state = {
    graph: null,
    selectedNodeId: "",
    criticalPath: new Set(),
    impacted: new Map(),
    filters: new Set(["requirement", "evidence", "offer", "profile", "application", "matching", "skill", "certification"]),
    view: { x: -40, y: -40, width: 880, height: 560 },
    loaded: false,
  };

  const TYPE_LABELS = {
    requirement: "Exigence",
    evidence: "Preuve",
    offer: "Offre",
    profile: "Profil",
    application: "Candidature",
    matching: "Matching",
    skill: "Compétence",
    certification: "Certification",
  };
  const TYPE_COLORS = {
    requirement: "#2f6f9f",
    evidence: "#2f8f6b",
    offer: "#9a6b1f",
    profile: "#6a4f9a",
    application: "#a33b3b",
    matching: "#3f7f86",
    skill: "#7a7a2f",
    certification: "#8f4f2f",
  };
  const IMPACT_COLORS = {
    critical: "#b3261e",
    high: "#c8551b",
    medium: "#a37a00",
    low: "#5f6b7a",
    none: "#9aa4af",
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  function setStatus(message, isError = false) {
    const node = byId("dependencies-status");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("is-error", Boolean(isError));
  }

  async function request(path, options) {
    const response = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    if (!response.ok) {
      const detail = payload && (payload.detail || payload.error);
      throw new Error(detail || `Requête locale refusée (${response.status}).`);
    }
    return payload;
  }

  function shortLabel(node) {
    const label = String((node && node.label) || (node && node.node_id) || "?");
    return label.length > 34 ? `${label.slice(0, 31)}…` : label;
  }

  function nodeTypeOf(nodeId) {
    return String(nodeId).split(":", 1)[0] || "requirement";
  }

  function visibleNodes() {
    if (!state.graph) return [];
    return Object.values(state.graph.nodes || {}).filter((node) => state.filters.has(node.node_type));
  }

  function visibleEdges(nodeIds) {
    if (!state.graph) return [];
    return (state.graph.edges || []).filter(
      (edge) => nodeIds.has(edge.source_id) && nodeIds.has(edge.target_id)
    );
  }

  function layout(nodes) {
    const nodesByType = new Map();
    nodes.forEach((node) => {
      const list = nodesByType.get(node.node_type) || [];
      list.push(node);
      nodesByType.set(node.node_type, list);
    });
    const types = [...nodesByType.keys()].sort();
    const positions = new Map();
    const width = Math.max(760, 220 * types.length);
    const height = Math.max(420, 90 + 150 * Math.max(...[...nodesByType.values()].map((list) => list.length), 1));
    const columnWidth = width / Math.max(types.length, 1);
    types.forEach((type, columnIndex) => {
      const list = nodesByType.get(type).sort((a, b) => String(a.node_id).localeCompare(String(b.node_id)));
      const rowHeight = height / (list.length + 1);
      list.forEach((node, rowIndex) => {
        positions.set(node.node_id, {
          x: columnWidth * (columnIndex + 0.5),
          y: rowHeight * (rowIndex + 1),
        });
      });
    });
    return { positions, width, height, types };
  }

  function svgElement(tag, attributes) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes || {}).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }

  function renderGraph() {
    const svg = byId("dependencies-svg");
    if (!svg) return;
    const nodes = visibleNodes();
    const ids = new Set(nodes.map((node) => node.node_id));
    const edges = visibleEdges(ids);
    svg.replaceChildren();

    const title = svgElement("title", {});
    title.textContent = "Graphe local des dépendances entre exigences, preuves, offres, candidatures et matchings.";
    svg.append(title);

    if (!nodes.length) {
      const empty = byId("dependencies-empty");
      if (empty) empty.hidden = false;
      svg.setAttribute("viewBox", "0 0 880 560");
      return;
    }
    const empty = byId("dependencies-empty");
    if (empty) empty.hidden = true;

    const computed = layout(nodes);
    state.view.width = computed.width;
    state.view.height = computed.height;
    state.view.x = 0;
    state.view.y = 0;
    applyViewBox();

    const defs = svgElement("defs", {});
    const marker = svgElement("marker", {
      id: "dependency-arrow",
      viewBox: "0 0 10 10",
      refX: "9",
      refY: "5",
      markerWidth: "6",
      markerHeight: "6",
      orient: "auto-start-reverse",
    });
    marker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#7b8794" }));
    const criticalMarker = svgElement("marker", {
      id: "dependency-arrow-critical",
      viewBox: "0 0 10 10",
      refX: "9",
      refY: "5",
      markerWidth: "7",
      markerHeight: "7",
      orient: "auto-start-reverse",
    });
    criticalMarker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#b3261e" }));
    defs.append(marker, criticalMarker);
    svg.append(defs);

    const edgeGroup = svgElement("g", { class: "dependency-edges" });
    edges.forEach((edge) => {
      const from = computed.positions.get(edge.source_id);
      const to = computed.positions.get(edge.target_id);
      if (!from || !to) return;
      const onCritical = state.criticalPath.has(edge.source_id) && state.criticalPath.has(edge.target_id);
      const line = svgElement("line", {
        x1: from.x,
        y1: from.y,
        x2: to.x,
        y2: to.y,
        class: onCritical ? "dependency-edge is-critical" : "dependency-edge",
        "stroke-width": Math.max(1, 1 + Number(edge.weight || 0) * 2),
        "marker-end": onCritical ? "url(#dependency-arrow-critical)" : "url(#dependency-arrow)",
      });
      const edgeTitle = svgElement("title", {});
      edgeTitle.textContent = `${edge.source_id} — ${edge.edge_type} (${Number(edge.weight || 0).toFixed(2)}) → ${edge.target_id}`;
      line.append(edgeTitle);
      edgeGroup.append(line);
    });
    svg.append(edgeGroup);

    const nodeGroup = svgElement("g", { class: "dependency-nodes" });
    nodes.forEach((node) => {
      const position = computed.positions.get(node.node_id);
      if (!position) return;
      const impact = state.impacted.get(node.node_id);
      const isSelected = state.selectedNodeId === node.node_id;
      const isCritical = state.criticalPath.has(node.node_id);
      const group = svgElement("g", {
        class: "dependency-node",
        transform: `translate(${position.x}, ${position.y})`,
        tabindex: "0",
        role: "button",
        "aria-label": `${TYPE_LABELS[node.node_type] || node.node_type} : ${node.label}`,
      });
      const radius = isCritical || isSelected ? 26 : 21;
      const circle = svgElement("circle", {
        r: radius,
        fill: TYPE_COLORS[node.node_type] || "#5f6b7a",
        stroke: impact ? IMPACT_COLORS[impact.impact_level] || "#9aa4af" : isCritical ? "#b3261e" : "#ffffff",
        "stroke-width": impact || isCritical ? 5 : 2,
        class: "dependency-node-circle",
      });
      const label = svgElement("text", {
        class: "dependency-node-label",
        y: radius + 17,
        "text-anchor": "middle",
      });
      label.textContent = shortLabel(node);
      const typeLabel = svgElement("text", {
        class: "dependency-node-type",
        y: radius + 32,
        "text-anchor": "middle",
      });
      typeLabel.textContent = TYPE_LABELS[node.node_type] || node.node_type;
      group.append(circle, label, typeLabel);
      group.addEventListener("click", () => selectNode(node.node_id));
      group.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectNode(node.node_id);
        }
      });
      nodeGroup.append(group);
    });
    svg.append(nodeGroup);

    const summary = byId("dependencies-summary");
    if (summary) {
      summary.textContent = `${nodes.length} nœud(s) affiché(s) · ${edges.length} lien(s) · version ${state.graph.version}`;
    }
    renderLegend();
  }

  function renderLegend() {
    const legend = byId("dependencies-legend");
    if (!legend) return;
    legend.replaceChildren();
    Object.entries(TYPE_LABELS).forEach(([type, label]) => {
      const item = element("span", "", "dependency-legend-item");
      const dot = element("span", "", "dependency-legend-dot");
      dot.style.background = TYPE_COLORS[type];
      item.append(dot, document.createTextNode(label));
      legend.append(item);
    });
    const critical = element("span", "", "dependency-legend-item");
    const criticalDot = element("span", "", "dependency-legend-dot dependency-legend-critical");
    critical.append(criticalDot, document.createTextNode("Chemin critique"));
    legend.append(critical);
  }

  function applyViewBox() {
    const svg = byId("dependencies-svg");
    if (!svg) return;
    const view = state.view;
    svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.width} ${view.height}`);
  }

  function selectNode(nodeId) {
    state.selectedNodeId = nodeId;
    renderGraph();
    renderNodeDetail(nodeId);
  }

  async function renderNodeDetail(nodeId) {
    const panel = byId("dependencies-node-detail");
    if (!panel) return;
    panel.replaceChildren();
    if (!nodeId) {
      panel.append(element("p", "Sélectionne un nœud pour voir ses voisins et ses liens.", "empty-state"));
      return;
    }
    try {
      const payload = await request(`/graph/nodes/${encodeURIComponent(nodeId)}`);
      const node = payload.node;
      const heading = element("h4", node.label);
      const type = element("p", `${TYPE_LABELS[node.node_type] || node.node_type} · ${node.node_id}`, "dependency-node-meta");
      panel.append(heading, type);
      if (Array.isArray(payload.neighbors.outgoing) && payload.neighbors.outgoing.length) {
        panel.append(element("p", "Sortants (dépend de ce nœud) :", "dependency-detail-label"));
        const outgoing = element("ul", "", "dependency-neighbor-list");
        payload.neighbors.outgoing.forEach((target) => outgoing.append(element("li", target)));
        panel.append(outgoing);
      }
      if (Array.isArray(payload.neighbors.incoming) && payload.neighbors.incoming.length) {
        panel.append(element("p", "Entrants (ce nœud dépend d'eux) :", "dependency-detail-label"));
        const incoming = element("ul", "", "dependency-neighbor-list");
        payload.neighbors.incoming.forEach((source) => incoming.append(element("li", source)));
        panel.append(incoming);
      }
      if (payload.edges.length) {
        panel.append(element("p", "Relations :", "dependency-detail-label"));
        const list = element("ul", "", "dependency-edge-list");
        payload.edges.forEach((edge) => {
          list.append(
            element("li", `${edge.source_id} — ${edge.edge_type} (${Number(edge.weight).toFixed(2)}) → ${edge.target_id}`)
          );
        });
        panel.append(list);
      }
    } catch (error) {
      panel.append(element("p", error.message, "dependency-error"));
    }
  }

  function populateSourceSelect() {
    const select = byId("dependencies-impact-source");
    if (!select || !state.graph) return;
    const selected = select.value;
    select.replaceChildren(new Option("Choisir un nœud…", ""));
    Object.values(state.graph.nodes || {})
      .sort((a, b) => String(a.node_id).localeCompare(String(b.node_id)))
      .forEach((node) => {
        select.append(new Option(`${TYPE_LABELS[node.node_type] || node.node_type} · ${shortLabel(node)}`, node.node_id));
      });
    if (selected) select.value = selected;
  }

  function renderImpact(payload) {
    const output = byId("dependencies-impact-output");
    if (!output) return;
    output.replaceChildren();
    const analysis = payload.analysis;
    state.criticalPath = new Set(analysis.critical_path || []);
    state.impacted = new Map((analysis.impacted_nodes || []).map((node) => [node.node_id, node]));
    renderGraph();

    const card = element("article", "", "dependency-impact-card");
    card.append(element("h4", `Impact de « ${analysis.change_type} » sur ${analysis.source_node_id}`));
    card.append(
      element(
        "p",
        `Profondeur ${analysis.propagation_depth} · charge relative ${analysis.estimated_total_effort} · ${analysis.impacted_nodes.length} nœud(s) impacté(s).`,
        "dependency-node-meta"
      )
    );
    if (analysis.breaking_changes.length) {
      const breaking = element("ul", "", "dependency-breaking-list");
      analysis.breaking_changes.forEach((message) => breaking.append(element("li", message)));
      card.append(element("p", "Ruptures potentielles (à relire, pas des certitudes) :", "dependency-detail-label"), breaking);
    }
    if (analysis.impacted_nodes.length) {
      const list = element("ul", "", "dependency-impact-list");
      analysis.impacted_nodes.forEach((node) => {
        const item = element("li", "", "dependency-impact-item");
        const badge = element("span", node.impact_level, "dependency-badge");
        badge.style.background = IMPACT_COLORS[node.impact_level] || "#5f6b7a";
        item.append(badge, element("strong", node.node_id), element("span", ` · effort ${node.estimated_effort}`));
        if (node.impact_reasons && node.impact_reasons.length) {
          item.append(element("p", node.impact_reasons[0], "dependency-node-meta"));
        }
        list.append(item);
      });
      card.append(list);
    } else {
      card.append(element("p", "Aucun impact au-dessus du seuil choisi. Ce n'est pas une garantie d'absence d'effet : vérifie le contexte.", "empty-state"));
    }
    output.append(card);

    const planButton = byId("dependencies-plan-button");
    if (planButton) {
      planButton.disabled = !analysis.recommended_order.length;
      planButton.dataset.nodeIds = JSON.stringify(analysis.recommended_order);
    }
  }

  async function runImpact() {
    const source = byId("dependencies-impact-source");
    const kind = byId("dependencies-impact-kind");
    const threshold = byId("dependencies-impact-threshold");
    if (!source || !source.value) {
      setStatus("Choisis d'abord un nœud source pour l'analyse d'impact.", true);
      return;
    }
    setStatus("Analyse d'impact locale…");
    try {
      const payload = await request("/impact", {
        method: "POST",
        body: JSON.stringify({
          source_node_id: source.value,
          change_type: (kind && kind.value) || "update",
          threshold: threshold ? Number(threshold.value) : 0.15,
        }),
      });
      renderImpact(payload);
      setStatus("Impact calculé localement : le graphe n'a pas été modifié.");
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function runPlan() {
    const button = byId("dependencies-plan-button");
    const output = byId("dependencies-plan-output");
    if (!button || !output) return;
    let nodeIds = [];
    try {
      nodeIds = JSON.parse(button.dataset.nodeIds || "[]");
    } catch (error) {
      nodeIds = [];
    }
    if (!nodeIds.length) {
      setStatus("Lance d'abord une analyse d'impact pour proposer un plan.", true);
      return;
    }
    try {
      const payload = await request("/plan", {
        method: "POST",
        body: JSON.stringify({ node_ids: nodeIds, action: "apply" }),
      });
      output.replaceChildren();
      const plan = payload.plan;
      output.append(element("h4", "Plan d'exécution ordonné"));
      output.append(element("p", plan.estimated_duration, "dependency-node-meta"));
      plan.parallel_groups.forEach((group, index) => {
        const card = element("section", "", "dependency-plan-group");
        card.append(element("h5", `Groupe parallèle ${index + 1}`));
        const list = element("ol");
        group.forEach((nodeId) => list.append(element("li", nodeId)));
        card.append(list);
        output.append(card);
      });
      if (plan.critical_path.length) {
        output.append(element("p", `Chemin critique : ${plan.critical_path.join(" → ")}`, "dependency-critical-path"));
      }
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function loadCritical() {
    const output = byId("dependencies-critical-output");
    if (!output) return;
    try {
      const payload = await request("/critical-nodes?top_n=8");
      output.replaceChildren();
      if (!payload.nodes.length) {
        output.append(element("p", "Aucun nœud critique : construis le graphe d'abord.", "empty-state"));
        return;
      }
      const list = element("ol", "", "dependency-critical-list");
      payload.nodes.forEach((node) => {
        const item = element("li");
        const points = node.single_point_of_failure ? " · point unique de fragilité" : "";
        item.append(element("strong", node.label), element("span", ` · score ${Number(node.score).toFixed(2)}${points}`, "dependency-node-meta"));
        if (node.reasons.length) item.append(element("p", node.reasons[0], "dependency-node-meta"));
        list.append(item);
      });
      output.append(list);
    } catch (error) {
      output.replaceChildren(element("p", error.message, "dependency-error"));
    }
  }

  async function loadFragility() {
    const output = byId("dependencies-fragility-output");
    if (!output) return;
    try {
      const [fragility, cycles] = await Promise.all([request("/fragility"), request("/cycles")]);
      output.replaceChildren();
      output.append(
        element(
          "p",
          `${fragility.node_count} nœud(s), ${fragility.edge_count} lien(s) · ${fragility.single_points_of_failure.length} point(s) de fragilité · ${cycles.count} cycle(s).`,
          "dependency-node-meta"
        )
      );
      if (fragility.isolated_nodes.length) {
        output.append(element("p", `Nœuds isolés : ${fragility.isolated_nodes.join(", ")}`, "dependency-node-meta"));
      }
      if (cycles.resolutions.length) {
        const list = element("ul", "", "dependency-cycle-list");
        cycles.resolutions.forEach((proposal) => {
          const edge = proposal.edge_id ? `${proposal.source_id} → ${proposal.target_id} (${proposal.edge_type})` : "arête inconnue";
          list.append(element("li", `Cycle ${proposal.cycle.join(" → ")} : retirer ${edge} ? ${proposal.reason}`));
        });
        output.append(list);
      } else {
        output.append(element("p", "Aucun cycle détecté.", "empty-state"));
      }
      output.append(element("p", fragility.disclaimer, "dependency-disclaimer"));
    } catch (error) {
      output.replaceChildren(element("p", error.message, "dependency-error"));
    }
  }

  async function buildGraph() {
    setStatus("Construction locale du graphe depuis les offres, exigences, preuves et candidatures…");
    try {
      const payload = await request("/graph", {
        method: "POST",
        body: JSON.stringify({ refresh_from_career: true, replace: true }),
      });
      state.graph = payload.graph;
      state.criticalPath = new Set();
      state.impacted = new Map();
      populateSourceSelect();
      renderGraph();
      setStatus(`Graphe construit localement (version ${payload.graph.version}). Aucune donnée n'a quitté ta machine.`);
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function snapshot() {
    try {
      const entry = await request("/snapshot", {
        method: "POST",
        body: JSON.stringify({ label: "depuis l'interface" }),
      });
      setStatus(`Snapshot v${entry.version} créé : rollback possible depuis l'historique.`);
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function loadGraph() {
    if (!byId("dependencies-svg")) return;
    setStatus("Chargement du graphe local…");
    try {
      const payload = await request("/graph");
      state.graph = payload.graph;
      state.loaded = true;
      populateSourceSelect();
      renderGraph();
      renderNodeDetail("");
      if (!Object.keys(payload.graph.nodes || {}).length) {
        setStatus("Aucun graphe enregistré. Clique sur « Construire / rafraîchir » pour l'assembler depuis tes données locales.");
      } else {
        setStatus(`Graphe local version ${payload.graph.version} · ${payload.graph.nodes ? Object.keys(payload.graph.nodes).length : 0} nœud(s).`);
      }
      loadCritical();
      loadFragility();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  function installControls() {
    byId("dependencies-build")?.addEventListener("click", buildGraph);
    byId("dependencies-refresh")?.addEventListener("click", loadGraph);
    byId("dependencies-snapshot")?.addEventListener("click", snapshot);
    byId("dependencies-impact-run")?.addEventListener("click", runImpact);
    byId("dependencies-plan-button")?.addEventListener("click", runPlan);
    byId("dependencies-critical-refresh")?.addEventListener("click", loadCritical);
    byId("dependencies-fragility-refresh")?.addEventListener("click", loadFragility);

    document.querySelectorAll("[data-dependency-filter]").forEach((input) => {
      input.checked = true;
      input.addEventListener("change", () => {
        if (input.checked) state.filters.add(input.dataset.dependencyFilter);
        else state.filters.delete(input.dataset.dependencyFilter);
        renderGraph();
      });
    });

    const svg = byId("dependencies-svg");
    if (svg) {
      svg.addEventListener(
        "wheel",
        (event) => {
          event.preventDefault();
          const factor = event.deltaY > 0 ? 1.12 : 0.89;
          const view = state.view;
          const nextWidth = Math.min(Math.max(view.width * factor, 180), 6000);
          const nextHeight = Math.min(Math.max(view.height * factor, 120), 4000);
          const rect = svg.getBoundingClientRect();
          const ratioX = Math.min(Math.max((event.clientX - rect.left) / Math.max(rect.width, 1), 0), 1);
          const ratioY = Math.min(Math.max((event.clientY - rect.top) / Math.max(rect.height, 1), 0), 1);
          view.x += (view.width - nextWidth) * ratioX;
          view.y += (view.height - nextHeight) * ratioY;
          view.width = nextWidth;
          view.height = nextHeight;
          applyViewBox();
        },
        { passive: false }
      );

      let drag = null;
      svg.addEventListener("pointerdown", (event) => {
        drag = { x: event.clientX, y: event.clientY, viewX: state.view.x, viewY: state.view.y };
        svg.setPointerCapture(event.pointerId);
      });
      svg.addEventListener("pointermove", (event) => {
        if (!drag) return;
        const scaleX = state.view.width / Math.max(svg.clientWidth, 1);
        const scaleY = state.view.height / Math.max(svg.clientHeight, 1);
        state.view.x = drag.viewX - (event.clientX - drag.x) * scaleX;
        state.view.y = drag.viewY - (event.clientY - drag.y) * scaleY;
        applyViewBox();
      });
      const stop = () => {
        drag = null;
      };
      svg.addEventListener("pointerup", stop);
      svg.addEventListener("pointercancel", stop);
    }
  }

  let installed = false;

  async function load() {
    if (!byId("dependencies-svg")) return;
    if (!installed) {
      installControls();
      installed = true;
    }
    await loadGraph();
  }

  window.CareerDependencies = { load, refresh: loadGraph, build: buildGraph };
})();
