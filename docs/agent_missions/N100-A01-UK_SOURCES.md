# MISSION N100-A01 — Connecteur UK (sources internationales finance)

## OBJECTIF
Créer un connecteur pour les offres de stages au Royaume-Uni (finance, M&A, CIB,
corporate finance) accessibles BBA/Bac+4, durée >=6 mois, à partir de janvier 2027.

## PÉRIMÈTRE
Crée `career/connectors/uk_sources.py` et `tests/test_uk_sources.py`.
Sources cibles (lecture publique uniquement) : Prospects, Gradcracker, TargetJobs.
Réutilise le pattern de `career/connectors/welcome_jungle.py` (SSL context, rate limit,
bounded fetch, HTML parser).

## CONTRAT
- ≥30 tests avec fixtures synthétiques (pas de réseau en test).
- Aucune donnée personnelle, aucun envoi, aucun auth.
- Respect 429 (backoff), User-Agent honnête.
- Normalisation via career/source_normalizer si disponible.
- Rapport `docs/agent-reports/N100-A01-UK_SOURCES.md`.
- Branche `agent/n100-A01-uk-sources`.

## LIVRABLES
1. Module + tests (≥30 cas).
2. Rapport docs/agent-reports/N100-A01-UK_SOURCES.md.
3. Push sur branche dédiée. EOF
echo "created A01"; cat > docs/agent_missions/N100-B05-DEGREE_LEVEL.md <<'EOF'
# MISSION N100-B05 — Niveau diplôme requis (BBA/Bac+4/M2/MBA)

## OBJECTIF
Détecter le niveau de diplôme requis par une offre : BBA, Bac+4, M1, M2, MBA,
PhD. Filtre clé pour l'utilisateur (BBA/Bac+4 accessible, conserver aussi M2/MBA).

## PÉRIMÈTRE
Crée `career/degree_level.py` et `tests/test_degree_level.py`.

## CONTRAT
- ≥30 cas de test (synthétiques).
- Fonction `detect_degree_level(text) -> str` retournant l'un de :
  "bba", "bac+4", "m1", "m2", "mba", "phd", "unknown".
- Heuristique locale (mots-clés : bachelor, master, mba, bba, bac+4, etc.).
- Rapport `docs/agent-reports/N100-B05-DEGREE_LEVEL.md`.
- Branche `agent/n100-B05-degree-level`.
