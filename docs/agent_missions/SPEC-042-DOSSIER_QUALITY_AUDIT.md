# MISSION CVBOOST-77 — SPEC-042 — Auditeur de qualité de dossier (anti-sur-promesse)

> **Priorité : P0** — Issue de l'audit externe 23/10 §4-1. Empêche des erreurs qui
> compromettent une candidature. Chaîné sur : 55/56/57 (produits), 38+46 (preuves), sk10 (profil).

## OBJECTIF
Pour tout document de candidature produit (CV adapté, lettre, réponses de formulaire),
émettre un **rapport de qualité** qui détecte : (1) les informations inventées,
(2) les formulations exagérées (« expert », « senior », anglicisms gonflés),
(3) les qualifications présentées hors contexte (un chiffre vrai resitué à autre chose),
(4) les arguments faibles (généricité, promesses non documentées), (5) le parasitage ATS
(mots-clés martelés sans contexte).

## PÉRIMÈTRE BUILD
Crée `career/dossier_quality.py`, `career/claim_check.py` et leurs tests.

FONCTIONS
1. `claim_check.py` : découpe le document en **claims phrasé par phrasé** ; chaque claim
   doit être démontrable par une preuve approuvée (source : service de preuves 38, niveau
   de preuve +<Date>), sinon label: [supported | inflated | out_of_context | invented |
   unverifiable]. Sortie JSON + rapport lisible avec phrase citée, preuve manquante,
   suggestion de reformulation (n'invente pas de suggestion : propose de s'appuyer sur
   les faits proposés déjà approuvés).
2. `dossier_quality.py` : scoring global (0-100) transparent : % de prévus validés,
   densité d'exagérations, preuve, argumentaire (identique aux questions réponses
   récurrentes et exigences de l'offre). Détaile les 3 facteurs et leur formule
   (99% factuel, transparence complète).
3. Règles exagération versionnées (fichier local editable par l'utilisateur) : interdits
   factuels (« expert » sans années appuyées), intéressment de la phrase (notamment
   promesse non-documented et mot de passe sentiment), repetition ATS (>3 fois le
   même keyword dans la même liste).
4. Intègre comme STEP du kit 1-clic (59) : un dossier est généré puis audité par la
   step 2 ; l'utilisateur voit l'audit AVANT d'exporter (le ROI : corrections en 30s
   au lieu d'être détectées par le recruteur).

## CONTRAT
- Aucune IA probabiliste pour le verdict final : règles locales déterministes + lexique.
- Test ≥ 60 cas : phrase inventée, légèrement outrée, hors contexte, chiffres déplacés,
  faibles (générique), ATS guessing, débordement KS bosse pas inventée du profil.
- Rapport `docs/agent-reports/CVBOOST-77-DOSSIER_QUALITY.md`
- Branche `agent/spec-042-dossier-quality`
