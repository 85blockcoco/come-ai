# Matrice de traçabilité des flashcards VC — NAGe

Date : 2026-11-03  
Périmètre : 170 cartes actives (5 packs existants + 15 packs ajoutés)

## Légende

- **Confiance** : Haute (source directe identifiée), Moyenne (source indirecte), Basse (définition standard, pas de citation paginée)
- **Anomalie** : problème détecté lors de la vérification

## Topics à haute confiance (sources directes identifiées)

| Topic | Cartes | Source vérifiable | Confiance | Anomalie |
|---|---|---|---|---|
| VC04 | VC04-C001 à C010 | `docs/vc_study/Topic 3 Valuation, ownership and returns(1).txt` ; papers 2023/2024/2025 | Haute | Aucune |
| VC05 | VC05-C001 à C010 | `docs/vc_study/Topic 3...txt` ; paper 2023 C16 | Haute | Aucune |
| VC07 | VC07-C001 à C010 | `docs/vc_study/Topic 4 Term sheets...txt` § liquidation ; papers | Haute | Aucune |
| VC09 | VC09-C001 à C010 | `docs/vc_study/Topic 3...txt` ; paper 2023 A15 | Haute | Aucune |

## Topics à confiance moyenne (source indirecte)

| Topic | Cartes | Source indirecte | Confiance | Anomalie |
|---|---|---|---|---|
| VC02 | VC02-C001 à C008 | paper 2023 B11 (waterfall) ; cours Topic 5 | Moyenne | Catch-up non paginé → `non vérifié` |
| VC03 | VC03-C001 à C010 | papers 2023/2024/2025 (staged financing) | Moyenne | Aucune |
| VC06 | VC06-C001 à C008 | paper 2025 A02/A08/A11/A12/A14 ; cours Topic 4 | Moyenne | Aucune |
| VC08 | VC08-C001 à C008 | paper 2025 A10 ; cours Topic 4 § ratchet | Moyenne | Formules anti-dilution non dans le corpus → définitions standard |
| VC13 | VC13-C001 à C008 | paper 2023 C17 (LBO) ; cours Topic 5 | Moyenne | Notions PE/M&A, pas VC pur → couverture partielle |
| VC14 | VC14-C001 à C008 | cours Topic 2 § burn rate | Moyenne | Définitions standard, pas de citation paginée |
| VC16 | VC16-C001 à C008 | paper 2023 B12 (convertibles) ; cours Topic 4 | Moyenne | Aucune |

## Topics à confiance basse (définitions standard, pas de source directe)

| Topic | Cartes | Source directe | Confiance | Anomalie |
|---|---|---|---|---|
| VC01 | VC01-C001 à C008 | Aucune identifiée | Basse | Cartes créées à partir de connaissances générales — à valider manuellement |
| VC10 | VC10-C001 à C008 | Aucune identifiée | Basse | Idem |
| VC11 | VC11-C001 à C008 | Aucune identifiée | Basse | Idem |
| VC12 | VC12-C001 à C008 | Aucune identifiée | Basse | Idem |
| VC15 | VC15-C001 à C008 | Aucune identifiée | Basse | Idem |
| VC17 | VC17-C001 à C008 | Aucune identifiée | Basse | Idem |
| VC18 | VC18-C001 à C008 | Aucune identifiée | Basse | Idem |
| VC19 | VC19-C001 à C008 | Aucune identifiée | Basse | Idem |
| VC20 | VC20-C001 à C008 | Aucune identifiée | Basse | Idem |

## Résumé

- **4 topics** : confiance haute (sources directes)
- **7 topics** : confiance moyenne (sources indirectes)
- **9 topics** : confiance basse (définitions standard)

**Action requise** : les 9 topics à confiance basse doivent être relus et validés contre les supports officiels avant l'examen. Les cartes sont pédagogiquement raisonnables mais non vérifiées.

## Sources disponibles (pour validation manuelle)

- `docs/vc_study/Topic 1 Introduction to venture capital and the VC ecosystem.txt`
- `docs/vc_study/Topic 2 Evaluating startups(1).txt`
- `docs/vc_study/Topic 3 Valuation, ownership and returns(1).txt`
- `docs/vc_study/Topic 4 Term sheets, deal structuring and negotiation(1).txt`
- `docs/vc_study/Topic 5 Governance, monitoring and exit strategies(1).txt`
- `docs/vc_study/Final exam 2023.txt` / `PEVC final exam 2023 (1).txt`
- `docs/vc_study/PEVC final exam 2024 solutions.txt`
- `docs/vc_study/VC final exam 2025 solutions.txt`
- `_vc_courses/Final exam 2023.pdf`
- `_vc_courses/PEVC final exam 2024 solutions.pdf`
- `_vc_courses/VC final exam 2025 solutions.pdf`
EOF
echo "done"

---

# Vérification Mission 2 (2026-11-03) — 9 topics à faible confiance

Méthode : chaque affirmation de carte a été recherchée dans le corpus
`docs/vc_study/*.txt` (recherche plein texte, citations = fichier:ligne).
Légende : **V** = vérifié (citation directe) · **P** = partiellement vérifié
(support indirect, formulation plus large que la source) · **NV** = non vérifié
(définition standard absente du corpus — à retenir comme connaissance générale,
pas comme cours cité).

## VC01 — Introduction à la VC

| Carte | Verdict | Citation |
|---|---|---|
| VC01-C001 What is venture capital | V | `Topic 1…txt:19-28` (minority, non-controlling, early/development-stage) |
| VC01-C002 Main players | V | `Topic 1…txt:136,150-153,276-289` (investor-type table) |
| VC01-C003 General partner (GP) | P | Rôle confirmé : `Background note - A rich-vs-king…txt:96` (fiduciary duty to LPs) ; définition textuelle = standard |
| VC01-C004 Limited partner (LP) | V | `rich-vs-king:96`, `Case - Navigating a Down Round…txt:120` (LP prospects) |
| VC01-C005 Angel investor | V | `rich-vs-king:32` (« wealthy individuals », invest personal capital) |
| VC01-C006 VC vs buyout | V | `Topic 1…txt:19-28` + `386-416` (table VC/growth/buyout : minority vs majority, leverage) |
| VC01-C007 Incubator | V | `Topic 1…txt:333-348` (table incubators) |
| VC01-C008 Accelerator | V | `Topic 1…txt:333-348` (fixed 3-6 months, 5-10% equity, seed funding) |

## VC10 — Processus d'investissement / term sheet

| Carte | Verdict | Citation |
|---|---|---|
| VC10-C001 Fundraising process | V | `Topic 1…txt:465-518` (sourcing → DD → term sheet → support ; F.I.R.E.) |
| VC10-C002 Due diligence | V | `Topic 1…txt:197-198,471-475` |
| VC10-C003 Pitch deck | P | `Topic 1…txt:468` (« pitch books ») ; terme « deck » absent |
| VC10-C004 Investment memo | V | `Gompers et al. 2020…txt:860-864` (memoranda describe thesis, risks, criteria) |
| VC10-C005 Investment committee | V | `Background note and sample - Notes on contents of a term sheet.txt:658,698` ; `Down Round…txt:300` |
| VC10-C006 Sourcing | V | `Topic 1…txt:467-470,368-373` (1,000+ proposals/an, networks) |
| VC10-C007 Negotiation timeline | NV | Absent du corpus |
| VC10-C008 No-shop clause | V | `Notes on contents of a term sheet.txt:176` |

## VC11 — Portefeuille

| Carte | Verdict | Citation |
|---|---|---|
| VC11-C001 Portfolio construction | V | `Topic 1…txt:391` (20-40+ portfolio firms) |
| VC11-C002 Reserve (follow-on) | NV | Concept absent ; contexte follow-on : `European Capital Map…txt:393` |
| VC11-C003 Follow-on | V | `Topic 1…txt:269` (follow-on funding rounds) ; `European Capital Map…txt:393` (70-100% follow-on) |
| VC11-C004 Pro rata | V | `rich-vs-king:636` ; `Notes on contents of a term sheet.txt:139-145` |
| VC11-C005 Power law | V | `Topic 1…txt:49` (« Power law returns (tail-heavy, feast-or-famine) ») |
| VC11-C006 Diversification | V | `Topic 1…txt:152,484` (club deals « to diversify risk ») |
| VC11-C007 Concentration limit | P | Exemple réel : `Down Round…txt:111` (~10% du Fund II) ; « limit » non définie |
| VC11-C008 Overage / opportunity fund | NV | Absent du corpus |

## VC12 — Gouvernance (board)

| Carte | Verdict | Citation |
|---|---|---|
| VC12-C001 Board seat | V | `Topic 1…txt:403-404` ; `Topic 5…txt:121` |
| VC12-C002 Observer right | V | `Topic 5…txt:149` ; `Down Round…txt:1446` |
| VC12-C003 Vesting 4y / 1y cliff | V | `rich-vs-king:651-656` (four-year, 25% first anniversary, then monthly) |
| VC12-C004 CEO replacement | V | `Topic 5…txt:270` (VCs can legally replace CEO) |
| VC12-C005 Information rights | V | `Notes on contents of a term sheet.txt:155` ; `Down Round…txt:1591-1592` |
| VC12-C006 Quorum | V | `Notes on contents of a term sheet.txt:117` ; `Sample - Share Subscription…txt:1343-1348` |
| VC12-C007 Conflict of interest | V | `Topic 1…txt:515` (governance: conflicts of interest) |
| VC12-C008 Independent director | V | `Sessions 5-6 Venture Capital.txt:1006` ; `Topic 4…txt:449` |

## VC15 — Modèles financiers

| Carte | Verdict | Citation |
|---|---|---|
| VC15-C001 Financial model | V | `Topic 2…txt:400-407,436-437` (plan 3-6 ans, inputs valuation/financing) |
| VC15-C002 Scenario analysis | NV | Absent du corpus |
| VC15-C003 Sensitivity analysis | NV | Absent du corpus |
| VC15-C004 Bottom-up forecasting | V | `Topic 2…txt:483-545` (table top-down vs bottom-up vs combined) |
| VC15-C005 Cash flow forecast | V | `Topic 2…txt:728` ; `Topic 1…txt:502` (burn rate → when/how much) |
| VC15-C006 Break-even | V | `Topic 2…txt:743,764` (cash-flow & accounting breakeven) |
| VC15-C007 Cap table model | P | `Topic 4…txt:107` (Cap Table / Share…) |
| VC15-C008 Waterfall model | V | `Final exam 2023.txt:213-218` (official model answer : capital → hurdle → catch-up → 80/20 → clawback) |

## VC17 — Écosystème européen / français

| Carte | Verdict | Citation |
|---|---|---|
| VC17-C001 Bpifrance | P | `European Capital Map…txt:8117-8137` (government office, Early Growth, France) ; fund-of-funds/garanties = standard, non cité |
| VC17-C002 EIF | P | `Startup Genome 2026…txt:6840,6920` (EU-level, EIF programs) |
| VC17-C003 French Tech | P | `European Capital Map…txt:1771,14225` ; `Startup Genome…txt:6969` (French Tech Mission) |
| VC17-C004 SAS | NV | Absent (uniquement suffixes de sociétés dans les annuaires) |
| VC17-C005 European hubs | P | Slide cours `Topic 1…txt:351` (« EUROPE'S LEADING START-UP HUBS », source FT) mais liste de villes non dans le texte |
| VC17-C006 ELTIF | NV | Absent du corpus |
| VC17-C007 VCT (UK) | NV | Définition absente (seule une société VCT en annuaire) |
| VC17-C008 Fund size | **V — carte corrigée** | `Topic 1…txt:393` : €100-€500m (la carte disait €50m-€500m → corrigée) |

## VC18 — Thèse, memo, évaluation

| Carte | Verdict | Citation |
|---|---|---|
| VC18-C001 Investment thesis | V | `Gompers et al. 2020…txt:860-861` (memoranda describe investment theses and risks) |
| VC18-C002 Memo components | P | `Gompers…txt:861-864` (team, market, competition, product/tech, business model) + `Topic 2…txt:238-248` (business-plan structure) |
| VC18-C003 Red flags | **V — carte corrigée** | `Topic 2…txt:227-231` (fatal flaws : no real customer need, unbeatable competition, poor team fit) — réponse réalignée sur le cours |
| VC18-C004 Competitive moat | P | `Topic 2…txt:132-135,173,178` (entry barriers, network externalities) ; le terme « moat » est absent |
| VC18-C005 Product-market fit | V | `Topic 1…txt:14,409` ; `Topic 2…txt:147-149` (need tested?) |
| VC18-C006 Traction | P | `Gompers…txt:879` (firm traction) ; définition = standard |
| VC18-C007 Go-to-market | V | `Topic 2…txt:190-195` (reach customers, marketing/distribution, pricing, acquisition/retention) |
| VC18-C008 Risk assessment | **V — carte corrigée** | `Topic 2…txt:138` (Market risk / Tech risk / People risk) — réponse réalignée sur les 3 risques du cours |

## VC19 — Venture debt

| Carte | Verdict | Citation |
|---|---|---|
| VC19-C001 Venture debt (existence) | P | `Topic 1…txt:289` (ticket €1-30m) ; `Sessions 5-6…txt:55` (investor type) |
| VC19-C002 Features (warrants…) | P/NV | Warrants : `Notes on contents of a term sheet.txt:78` ; interest-only/covenants = non vérifié |
| VC19-C003 Why startups use it | NV | Absent |
| VC19-C004 Warrant | P | `Notes on contents of a term sheet.txt:78` (« warrants exercisable up to some future date ») |
| VC19-C005 Interest-only period | NV | Mention seulement : `PEVC final exam 2024 solutions.txt:133` |
| VC19-C006 Risk of venture debt | NV | Absent |
| VC19-C007 Revenue-based financing | NV | Absent |
| VC19-C008 When appropriate | NV | Absent |

> **AVERTISSEMENT EXAMEN** : VC19 est le topic le moins couvert par le corpus.
> Traiter ses 8 cartes comme connaissance générale, pas comme cours.

## VC20 — Stratégie d'examen

| Carte | Verdict | Citation |
|---|---|---|
| VC20-C001 Approach (read all first…) | NV | Conseil de stratégie (non citable) |
| VC20-C002 Exam structure | V | `VC final exam 2025 solutions.txt:46,150,242` (A : 15 MCQ · B : 15 calculations · C : 30 case studies) |
| VC20-C003 Numerical method | V | `VC final exam 2025 solutions.txt:151` (« SHOW YOUR CALCULATIONS ») |
| VC20-C004 Common traps | P | Pre/post-money : `Topic 3…txt` + Q7 2025 (`VC final exam 2025 solutions.txt:88-96`) |
| VC20-C005 90-minute time mgmt | V (durée) / NV (répartition) | Durée : `Topic 1…txt:109` (« Final exam … 90 minutes ») ; répartition = conseil |
| VC20-C006 Show calculations | V | `VC final exam 2025 solutions.txt:151` ; `PEVC final exam 2024 solutions.txt:48-49` (formulas must be shown) |
| VC20-C007 If stuck, move on | NV | Conseil de stratégie |
| VC20-C008 Verify answers | NV | Conseil de stratégie |

### Bilan Mission 2

- **Cartes vérifiées (V)** : 41/72 · **partielles (P)** : 17/72 · **non vérifiées (NV)** : 14/72
- **3 cartes corrigées** : VC17-C008 (fund size €100-€500m d'après Topic 1:393),
  VC18-C003 et VC18-C008 (réalignées sur la formulation du cours Topic 2).
- **14 cartes NV** listées ci-dessus : à retenir comme connaissances standard,
  **non citables comme cours** (VC07 timeline, VC11 reserve/overage, VC15
  scenario/sensitivity, VC17 SAS/ELTIF/VCT, VC19 quasi-intégralement, VC20
  conseils de stratégie).

---

# Correction des drills anti-dilution (VC08) — Mission 2

- **Corpus** : `Background note - A rich-vs-king…txt:288-321` (définition full
  ratchet vs weighted average ; broad-based = inclut les options, présent dans
  88-92% des deals ; narrow-based = exclut les options, 2-3% ; broad plus
  favorable à l'entrepreneur) et `Case - Navigating a Down Round…txt:1157-1175`
  (glossary anti-dilution : taille du down round → ampleur de l'ajustement).
- **La formule CP2 = CP1 × (A + B) / (A + C) n'est PAS dans le corpus** : c'est
  la convention standard de marché. Les drills l'utilisent ; la convention
  (broad/narrow) est citée, la formule est à considérer comme standard.
- **VC08-D003 réécrit** : le prompt ditait « weighted-average price » avec une
  moyenne share-weighted non située ; il pose désormais explicitement un prix de
  conversion **broad-based** (A as-converted, B = new money / CP1, C = new
  shares) + 3 error paths (moyenne naive, full ratchet, pas de mouvement).
  Réponse inchangée : 4.00.
- **VC08-D005 ajouté** : broad vs narrow avec option pool (1,000,000 common +
  200,000 options, CP1 $4, new money $800k, 400,000 new shares @ $2) :
  broad = **$3.50** (attendu), narrow = $3.43 (accepted via
  `alternative_conventions`, avec explication), error paths 3.00 (moyenne
  naive) et 2.00 (full ratchet). Vérifié par grading : les 4 cas passent.

---

# Fiabilité des annales (Mission 2) — clé de réponse MCQ

**Constat** : les fichiers officiels (`VC final exam 2025 solutions.txt`,
`PEVC final exam 2024 solutions.txt`, `PEVC final exam 2023 (1).txt`,
`Final exam 2023.txt`) **ne marquent aucune réponse MCQ** (toutes les
checkboxes identiques, aucun key). Les solutions officielles couvrent les
sections B/C (calculs et cas, tableaux retravaillés reproduits dans les packs).

**Conséquence** : les lettres MCQ des packs `paper_2023/2024/2025.json` sont
**déduites** (inférées à la création du pack), pas officielles.

**Actions** :
1. Les trois `notice` de packs signalent explicitement : « the MCQ answer key
   in this pack is derived (inferred), not official — treat MCQ grading as
   practice only; the worked/numerical solutions are reproduced from the
   official file. »
2. UI (`revisions.js`) : les réponses MCQ des solutions portent le badge
   orange **« Derived key »**, les solutions travaillées le badge vert
   **« Official »** ; le bandeau de notice s'affiche dans la vue solutions et
   le résultat de correction (badge **« Pack answer key »**).
3. Le bouton est renommé **« Solutions & key »** (plus « Official solutions »).
4. Les solutions ouvertes **O** restent officielles : citations ex.
   `Final exam 2023.txt:213-218` (waterfall/catch-up/clawback).

**Résidu clairement étiqueté** : toute note MCQ = pratique avec clé dérivée ;
toute note B/C = corrigé officiel.
