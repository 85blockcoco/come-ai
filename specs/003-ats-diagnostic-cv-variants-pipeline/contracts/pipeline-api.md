# Contract: Application Pipeline API Endpoint

**Feature**: 003-ats-diagnostic-cv-variants-pipeline
**Version**: 1.0
**Date**: 2026-10-21

---

## Endpoint

```
GET /api/career/application-pipeline
```

**Authentication**: None (local-only server, Constitution Principle III)
**Rate Limit**: N/A (local)
**Response Format**: JSON

---

## Request

No parameters required. Optional query params for future filtering:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `stage` | string | all | Filter by pipeline stage |
| `variant` | string | all | Filter by CV variant |
| `limit` | int | 100 | Max items returned |

---

## Response

### Success (200)

```json
{
  "pipeline": [
    {
      "job_id": "jpm-2027-iba",
      "company": "JPMorgan",
      "title": "Investment Banking Analyst Intern",
      "stage": "kit_generated",
      "variant": "m_a",
      "variant_label": "M&A / Investment Banking",
      "kit_generated_at": "2026-10-21T14:30:00Z",
      "tracking_stage": null,
      "readiness": "prepare_now",
      "match_score": 87
    },
    {
      "job_id": "gs-2027-strats",
      "company": "Goldman Sachs",
      "title": "Strategist Intern",
      "stage": "prep_analyzed",
      "variant": null,
      "variant_label": null,
      "kit_generated_at": null,
      "tracking_stage": null,
      "readiness": "offer_to_verify",
      "match_score": 72
    },
    {
      "job_id": "bnpp-2027-fpna",
      "company": "BNP Paribas",
      "title": "FP&A Analyst Intern",
      "stage": "tracking_created",
      "variant": "corporate_finance",
      "variant_label": "Corporate Finance / FP&A",
      "kit_generated_at": "2026-10-20T10:15:00Z",
      "tracking_stage": "to_prepare",
      "readiness": "profile_to_complete",
      "match_score": 65
    }
  ],
  "automatic_submission": false
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | string | Primary key from `jobs` table |
| `company` | string | `jobs.company` |
| `title` | string | `jobs.title` |
| `stage` | enum | Derived stage (see Stage Derivation Logic) |
| `variant` | string/null | `application_drafts.variant` or sprint recommendation |
| `variant_label` | string/null | Human-readable variant label |
| `kit_generated_at` | ISO8601/null | `application_drafts.created_at` when variant selected |
| `tracking_stage` | string/null | `applications.stage` if tracking exists |
| `readiness` | string | From sprint queue: `prepare_now`, `profile_to_complete`, `offer_to_verify`, `candidate_to_verify` |
| `match_score` | int | From sprint queue (0-100) |
| `automatic_submission` | boolean | Always `false` (Constitution Principle II) |

---

## Stage Derivation Logic (Pure Function)

```python
def derive_pipeline_items(
    jobs: dict[str, dict],                           # All jobs from jobs table
    stage_matches: list[dict],                       # From list_stage_matches()
    sprint_queue: list[dict],                        # From get_application_sprint()
    prep_cache: dict[str, dict],                     # job_id -> get_job_prep() result
    application_drafts: list[dict],                  # From application_drafts table
    applications: list[dict]                         # From applications table
) -> list[PipelineItem]:

    # Build lookup maps
    sprint_by_job = {item["job_id"]: item for item in sprint_queue}
    draft_by_job = {d["job_id"]: d for d in application_drafts}
    app_by_job = {a["job_id"]: a for a in applications}
    qualified_jobs = {jid for jid, job in jobs.items() if job.get("qualification_facts_json")}

    items = []
    for job_id, job in jobs.items():
        # Determine stage (priority order)
        if job_id in app_by_job:
            stage = PipelineStage.TRACKING_CREATED
        elif job_id in draft_by_job:
            stage = PipelineStage.KIT_GENERATED
        elif job_id in prep_cache and draft_by_job.get(job_id, {}).get("variant"):
            stage = PipelineStage.VARIANT_SELECTED
        elif job_id in prep_cache:
            stage = PipelineStage.PREP_ANALYZED
        elif job_id in sprint_by_job:
            stage = PipelineStage.SPRINT_QUEUED
        elif job_id in qualified_jobs:
            stage = PipelineStage.QUALIFIED
        else:
            stage = PipelineStage.DISCOVERED

        # Variant info
        variant = None
        variant_label = None
        kit_generated_at = None
        if job_id in draft_by_job:
            variant = draft_by_job[job_id].get("variant")
            variant_label = VARIANT_LABELS.get(variant)
            kit_generated_at = draft_by_job[job_id].get("created_at")

        # Tracking stage
        tracking_stage = app_by_job[job_id].get("stage") if job_id in app_by_job else None

        # Sprint info
        sprint_item = sprint_by_job.get(job_id, {})
        readiness = sprint_item.get("readiness")
        match_score = sprint_item.get("match_score", 0)

        items.append(PipelineItem(
            job_id=job_id,
            company=job.get("company", "Inconnu"),
            title=job.get("title", "Sans titre"),
            stage=stage,
            variant=variant,
            variant_label=variant_label,
            kit_generated_at=kit_generated_at,
            tracking_stage=tracking_stage,
            readiness=readiness,
            match_score=match_score
        ))

    # Sort: tracked first, then by stage priority, then match_score desc
    stage_priority = {
        PipelineStage.TRACKING_CREATED: 0,
        PipelineStage.KIT_GENERATED: 1,
        PipelineStage.VARIANT_SELECTED: 2,
        PipelineStage.PREP_ANALYZED: 3,
        PipelineStage.SPRINT_QUEUED: 4,
        PipelineStage.QUALIFIED: 5,
        PipelineStage.DISCOVERED: 6,
    }
    items.sort(key=lambda x: (stage_priority[x.stage], -x.match_score, x.company.lower()))

    return items
```

---

## Data Sources (Read-Only)

| Table/View | Columns Used | Purpose |
|------------|--------------|---------|
| `jobs` | `id`, `company`, `title`, `qualification_facts_json` | Base offer data + qualification status |
| `stage_matches` | `job_id`, `qualification_status`, `score` | Sprint queue membership |
| `application_drafts` | `job_id`, `variant`, `created_at`, `language` | Kit generation tracking |
| `applications` | `job_id`, `stage` | Manual tracking status |

**Note**: `application_drafts` may need `variant` column added via additive migration:
```sql
ALTER TABLE application_drafts ADD COLUMN variant TEXT;
```

---

## Frontend Integration (career.js)

### New Panel in index.html

```html
<section class="panel stagehunter-pipeline-panel">
  <div class="panel-heading">
    <div>
      <p class="eyebrow">Cycle complet</p>
      <h3>Suivi de bout en bout : offre → qualification → CV adapté → lettre → suivi</h3>
    </div>
    <button id="stagehunter-pipeline-refresh" class="secondary-button" type="button">Actualiser</button>
  </div>
  <p class="fixed-period-note">Vue unifiée de toutes vos offres traitées. Aucun envoi automatique.</p>
  <div id="stagehunter-pipeline" class="stagehunter-pipeline" aria-live="polite" hidden></div>
</section>
```

### Render Function

```javascript
async function loadApplicationPipeline() {
  const target = $("#stagehunter-pipeline");
  target.hidden = false;
  target.replaceChildren(make("p", "Chargement du pipeline…"));
  try {
    const payload = await api("/api/career/application-pipeline");
    renderApplicationPipeline(payload);
  } catch (error) {
    target.replaceChildren(make("p", error.message, "scoring-disclaimer"));
  }
}

function renderApplicationPipeline(payload) {
  const target = $("#stagehunter-pipeline");
  target.replaceChildren();

  const pipeline = payload.pipeline || [];
  if (!pipeline.length) {
    target.append(make("p", "Aucune offre dans le pipeline. Lancez une recherche et construisez votre liste express.", "empty-state"));
    return;
  }

  const table = make("table", "", "pipeline-table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>Entreprise</th>
        <th>Intitulé</th>
        <th>Stade</th>
        <th>Variante CV</th>
        <th>Kit généré</th>
        <th>Suivi</th>
        <th>Prêt</th>
        <th>Score</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = table.querySelector("tbody");

  pipeline.forEach(item => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(item.company)}</td>
      <td>${escapeHtml(item.title)}</td>
      <td><span class="pipeline-badge pipeline-${item.stage}">${stageLabel(item.stage)}</span></td>
      <td>${item.variant_label || "—"}</td>
      <td>${item.kit_generated_at ? formatDate(item.kit_generated_at) : "—"}</td>
      <td>${item.tracking_stage || "—"}</td>
      <td>${readinessLabel(item.readiness)}</td>
      <td>${item.match_score}</td>
      <td class="pipeline-actions"></td>
    `;

    const actionsTd = tr.querySelector(".pipeline-actions");
    if (item.stage === "kit_generated" && !item.tracking_stage) {
      const trackBtn = make("button", "Créer le suivi", "secondary-button");
      trackBtn.onclick = () => createTracking(item.job_id);
      actionsTd.append(trackBtn);
    }
    if (item.stage === "prep_analyzed" || item.stage === "sprint_queued") {
      const prepBtn = make("button", "Préparer", "primary-button");
      prepBtn.onclick = () => loadStagePrep(item.job_id);
      actionsTd.append(prepBtn);
    }
    if (item.variant && item.stage >= "variant_selected") {
      const kitBtn = make("button", "Voir le kit", "secondary-button");
      kitBtn.onclick = () => openKitFolder(item.job_id, item.variant);
      actionsTd.append(kitBtn);
    }

    tbody.append(tr);
  });

  target.append(table);
  reveal(target, "start");
}
```

### Stage Labels (FR)

```javascript
const STAGE_LABELS = {
  discovered: "Découverte",
  qualified: "Qualifiée",
  sprint_queued: "En file express",
  prep_analyzed: "Analyse prête",
  variant_selected: "Variante choisie",
  kit_generated: "Kit généré",
  tracking_created: "Suivi créé"
};
```

---

## Error Responses

| Status | Body |
|--------|------|
| 500 | `{"detail": "Erreur interne: ..."}` |

---

## Test Contract

```python
def test_pipeline_endpoint_returns_all_stages(tmp_path):
    svc = CareerService(tmp_path)
    # Setup: 3 jobs at different stages
    # job1: discovered only
    # job2: qualified + in sprint
    # job3: kit_generated + tracking
    app = create_app(base_dir=tmp_path, career_override=svc)

    with TestClient(app) as client:
        resp = client.get("/api/career/application-pipeline")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["pipeline"]) == 3
        assert data["automatic_submission"] is False

        stages = {item["job_id"]: item["stage"] for item in data["pipeline"]}
        assert stages["job1"] == "discovered"
        assert stages["job2"] == "sprint_queued"
        assert stages["job3"] == "tracking_created"

        # Kit generated item has variant
        kit_item = next(i for i in data["pipeline"] if i["job_id"] == "job3")
        assert kit_item["variant"] == "corporate_finance"
        assert kit_item["kit_generated_at"] is not None

def test_pipeline_sort_order():
    # Tracked first, then by stage priority, then match_score desc
    items = derive_pipeline_items(...)
    assert items[0].stage == PipelineStage.TRACKING_CREATED
    assert items[-1].stage == PipelineStage.DISCOVERED
```

---

*Contract complete. Implementation in `career/service.py::get_application_pipeline` + `career_static/career.js::renderApplicationPipeline`.*
