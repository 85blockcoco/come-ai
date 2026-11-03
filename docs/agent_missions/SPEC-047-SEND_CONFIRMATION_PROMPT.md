# MISSION SPEC-047 — Confirmation d'envoi humaine + relance optimale

> **Priorité : P0** — Après le clic humain : enregistrer l'envoi, relancer au bon moment.
> **Règle absolue : aucune soumission automatique, jamais.** L'humain confirme ; le module enregistre.

## Mission — `career/send_confirmation.py`
- `record_send(job_id, evidence: SendEvidence) -> SendRecord` :
  evidence = canal (website/email/portal), sent_at, note optionnelle.
  Persist via le store existant (application_dashboard/store), MAJ tracking_stage → "sent"
  seulement après confirmation humaine.
- Anti-fraude : sent_at > 24 h dans le futur → erreur métier ; double envoi → idempotent
  (mise à jour) sans dupliquer l'historique.
- `follow_up_due` = +7 jours ouvrés (week-ends exclus) ; si relance déjà faite → prochaine +7j.
- `build_followup_draft(job_id) -> str` : template de relance court, prêt à copier, français.
- Endpoints : `POST /api/career/send-confirmation/{job_id}` ;
  `GET /api/career/apply-tracker` → envoyés sans réponse, à relancer (priorisés par due date).

## Contrats
```python
@dataclass
class SendEvidence: channel: Literal["website","email","portal"] ; sent_at: datetime ; note: str | None = None
@dataclass
class SendRecord: job_id: str ; sent_at: datetime ; channel: str ; follow_up_due: datetime
```

## Livrables
1. Module + endpoints, smoke test.
2. Tests : envoi valide ; futur >24 h → erreur ; idempotence ; +7 jours ouvrés (multi-cas : vendredi→lundi, jour férié ignoré si hors données).
3. Ruff ; fixtures synthétiques ; push sur `agent/spec-047-send-confirmation`.

## Cadre commun (toutes missions, non négociable)
- Aucune soumission automatique de candidature ; aucune donnée réelle.
- Tests ciblés vert + `ruff check career/` ; ne pas lancer la suite complète pendant les jobs en fond.
- API via le pattern career existant, ne pas casser `schema_version=7`.
- Push UNIQUEMENT sur ta branche dédiée (jamais main) ; preuve = branche poussée + tests rejoués.
- Rapport succinct dans `docs/agent-reports/`.
