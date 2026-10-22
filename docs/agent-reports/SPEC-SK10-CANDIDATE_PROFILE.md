# SPEC-SK10 — Profil candidat avec preuves approuvées

**Mission** : CVBOOST-31 — SK-10 — **campagne adversariale n°2** (ordre `cvboost-31-1792623192`)
**Branche** : `worker/cvboost-31-1792623192` → reprise sur `agent/spec-sk10-candidate-profile`
**Base** : `main` (`f5b22f2` — merge(career): ATS diagnostics and targeted CV variants pipeline)
**Suite** : 1503 tests verts (1482 avant campagne, +21 tests adversariaux), 1 skip préexistant
**Lint** : `ruff check .` → All checks passed · `git diff --check` → propre · `checklist_codex.sh` → TOUT VERT

> **Cette campagne ne crée aucune v3.** La livraison canonique
> (`0502c4b` → `ac72b82` → `a52bae3` → `1d2f73c`) est reprise telle quelle :
> les six défauts déjà corrigés (D1–D6) restent corrigés et testés. Cette
> campagne attaque les zones que la première n'avait pas couvertes et trouve
> **six nouveaux défauts réels** (D7–D12), tous reproduits puis corrigés dans
> les modules existants. Voir §2 bis.

---

## 0. Recherche préalable : ce qui existait déjà

Trois implémentations parallèles de SK-10 existaient avant cette tentative. Aucune
n'a été recopiée à l'aveugle : la plus complète a été relue ligne à ligne, les
autres ont servi de contre-épreuve.

| Tentative | Contenu | Décision |
|-----------|---------|----------|
| `agent/spec-sk10-candidate-profile` (`0502c4b`) | Livraison canonique : modèle, builder, service, UI, 38 tests | **Reprise** (cherry-pick propre, base identique) puis auditée et corrigée |
| `worker/cvboost-31-1792614191` (`3fc6b07`) | Implémentation indépendante, dossier de fixtures différent | Non retenue : structure divergente, moins de garanties |
| `worker/cvboost-31-1792615600` (`c029b15`) | Autre implémentation indépendante, tables et statuts différents | Non retenue : même conclusion |
| `agent/spec-sk10-candidate-profile` (`1d2f73c`, campagne n°1) | Livraison canonique + audit adversarial n°1 (D1–D6) | **Reprise telle quelle** : base de cette campagne |
| `worker/cvboost-31-1792617513` (`7298ebc`) | Consolidation parallèle de la lignée `c029b15` | Non retenue : même base, garanties moindres |
| `worker/cvboost-31-1792617672` (`1d2f73c`) | Campagne adversariale n°1 (D1–D6) | **Consolidée** : c'est la tête de `origin/agent/spec-sk10-candidate-profile` |

**Aucune v3 n'a été créée** : les corrections sont faites dans les modules
existants de la livraison canonique.

> **Note de fusion** — pendant ce travail, la branche de mission a avancé
> (`ac72b82` : application des faits de contact approuvés au profil, c'est-à-dire
> D2 ci-dessous). Le travail a été **rebasesé sur cette tête** au lieu de
> l'écraser : la branche `agent/spec-sk10-candidate-profile` avance par
> fast-forward, sans force-push, et le correctif de contact y est conservé.

> **Note de consolidation (campagne n°2)** — `git fetch` a montré que
> `origin/agent/spec-sk10-candidate-profile` avait avancé jusqu'à `1d2f73c`
> (campagne adversariale n°1). La branche de travail a été amenée par
> **fast-forward sur cette tête** avant toute écriture : la campagne n°2
> démarre donc sur le code **le plus avancé**, pas sur la version initiale.
> Aucune implémentation parallèle n'a été recopiée.

Cette tentative apporte ce que la livraison précédente ne contenait pas :

- **un audit adversariel** qui a trouvé 6 défauts réels (section 2), tous
  corrigés dans les modules existants ;
- **un apply réversible** : un fait appliqué puis rejeté, mis de côté, rouvert ou
  supprimé **cesse de justifier une candidature** — c'était le défaut le plus
  grave, il touchait le critère bloquant de la mission ;
- **une provenance au caractère près** : la citation stockée est désormais le
  texte source exact (`source[start:end]`), sans espace normalisé en douce ;
- **une page honnête** : un DOCX ou une lecture OCR n'affichent plus une page
  « exacte » qu'ils ne peuvent pas prouver.

La **campagne n°2** (cette livraison) ajoute par-dessus :

- **des offsets qui désignent le texte réellement montré à la personne**
  (D7) — le cas le plus courant, un PDF de plusieurs pages, était décalé ;
- **la preuve d'une date** : les offsets désignent la date et non l'entrée
  entière (D8) ;
- **des rubriques que rien ne peut voler** : une phrase de résumé qui mentionne
  une rubrique ne peut plus faire disparaître les compétences (D9) ;
- **une borne de champ qui ne jette pas un fait qui tient** (D10) ;
- **deux documents qui ne s'effacent pas** (D11) ;
- **une citation toujours verbatim** (D12).

---

## 1. Objectif

Transformer le CV importé en **profil structuré contrôlé par la personne** :

```
PDF / DOCX / image
  → extraction locale (parser Mission 01)
  → OCR local si nécessaire
  → propositions de faits (compétences, expériences, formation, langues, dates…)
  → provenance page / passage (offsets exacts)
  → approbation champ par champ (UI)
  → profil actif (seuls faits approuvés)
```

Les six critères non négociables de la mission sont **structurels**, pas des
conventions documentées : ils sont garantis par le code et prouvés par les
tests (section 6).

---

## 2. Audit adversarial (campagne n°1) : 6 défauts trouvés, 6 corrigés

> Cette section décrit la **campagne n°1**, reprise telle quelle. Les six
> défauts qu'elle a trouvés (D1–D6) restent corrigés et testés. La campagne
> n°2 (§2 bis) en trouve six autres (D7–D12).

La livraison reprise a été soumise à une campagne de scénarios-hostiles. Chaque
défaut a été **reproduit** avant d'être corrigé, puis figé en test de
non-régression.

### D1 — Un fait appliqué puis rejeté continuait de justifier une candidature 🔴

**Reproduit** : `build → approve → apply → reject` laissait la ligne dans le
champ `skills` du profil. Le brouillon de candidature affichait donc toujours la
compétence rejetée — exactement ce que le critère 5 interdit.

**Cause** : l'« apply » écrivait dans le profil sans jamais mémoriser ce qu'il
avait écrit. Aucune décision ultérieure ne pouvait donc pas revenir en arrière.

**Correction** : le service retient désormais le champ et la ligne exacte que
chaque fait a écrits (`candidate_facts.applied_field` / `applied_line`, schéma
v10). Un fait rejeté, mis de côté, rouvert ou supprimé voit sa ligne retirée du
profil ; une correction remplace la ligne par la nouvelle ; si une ligne était
partagée avec un autre fait approuvé, elle **change de main** au lieu de
disparaître.

### D2 — Un fait de contact approuvé n'était jamais écrit dans le profil 🟠

**Reproduit** : `merge_usable_facts()` complétait `contact_email`, mais
`apply_candidate_facts()` ne sauvegardait que `education`, `experience`, `skills`
et `languages`. L'e-mail du CV disparaissait, et la réponse affirmait pourtant
« appliqué : 1 ».

> Ce défaut a été corrigé entre-temps sur la branche de mission (`ac72b82`).
> La correction est conservée et complétée ici.

**Correction** : les champs de contact sont persistés, et le résultat distingue
`applied` (faits présents dans le profil), `written` (faits qui y ont réellement
écrit) et `ignored` (faits sans place dans les champs, comme une date).

### D3 — Une rubrique saturée effaçait toutes les autres 🟠

**Reproduit** : au-delà de 60 faits d'un même type, la boucle de bornage
s'interrompait (`break`) : les rubriques **Langues**, **Formation** et
**Expérience** disparaissaient entièrement du bilan de relecture.

**Correction** : une rubrique à son plafond est **sautée**, jamais fatale pour le
reste du document.

### D4 — La citation n'était pas le passage source 🔴

**Reproduit** : sur une ligne contenant des espaces répétés
(`Python   et   SQL`), la citation stockée était `Python et` alors que les
offsets pointaient sur `Python   et   SQL`. La citation n'était donc pas le
passage annoncé par les offsets — le critère 2 n'était pas tenu.

**Correction** : les offsets sont calculés sur le texte **brut** (jamais sur une
version normalisée) et la citation est le texte source verbatim. Le libellé
affiché reste normalisé, la preuve ne l'est jamais.

### D5 — Un DOCX ou une lecture OCR affichait une page « exacte » 🟠

**Reproduit** : un DOCX n'a pas d'information de page ; le module en annonçait
toutefois une, avec la confiance `exact`. Un import OCR pouvait aussi être
relu par le parser au lieu de la lecture OCR réellement montrée à la personne.

**Correction** : un DOCX reste `estimated`, l'OCR garde sa lecture stockée, et
l'interface affiche « (estimée) » quand la page n'est pas prouvée.

### D6 — L'interface ne permettait pas de corriger un fait déjà approuvé 🟡

**Reproduit** : le bouton « Corriger » n'existait que pour un fait `proposed`.
Un fait approuvé — donc déjà dans le profil — ne pouvait plus être rectifié,
alors que la machine à états l'autorise.

**Correction** : « Corriger » est proposé pour un fait approuvé ou corrigé.

---

## 2 bis. Campagne adversariale n°2 : 6 nouveaux défauts trouvés, 6 corrigés

La campagne n°1 avait audité le **modèle**, l'**apply réversible** et la
**page honnête**. Elle n'avait pas encore mis la **preuve** à l'épreuve : est-ce
que les offsets désignent réellement le texte que la personne a sous les yeux ?
est-ce qu'une date désigne la date ? est-ce qu'une rubrique peut disparaître ?

Chaque défaut ci-dessous a été **reproduit par un test** sur le code livré
(`git stash` des corrections → le test échoue), puis **corrigé dans les
modules existants**, puis **figé en test de non-régression**.

### D7 — Les offsets ne désignaient pas le texte montré à la personne 🔴

**Reproduit** : le service relisait le document stocké pour retrouver les pages,
et construisait les faits sur **cette relecture**. Or la relecture n'est pas la
lecture affichée dans l'aperçu :

| Cas | Lecture de l'aperçu | Lecture du builder | Écart |
|-----|---------------------|--------------------|-------|
| TXT | texte **rogné** (`extract_text(...).strip()`) | texte brut | décalage de l'en-tête |
| DOCX | texte **rogné** | texte brut | idem |
| **PDF multipage** | pages jointes par **un** `\n` | pages jointes par **deux** `\n` | **+1 caractère par page** |

Conséquence : sur un PDF de deux pages et plus — le cas le plus courant — les
offsets de tous les faits des pages suivantes pointaient **n'importe où** dans
l'aperçu, et la preuve était invérifiable. Le critère 2 n'était pas tenu.

**Correction** : la lecture **stockée** (celle de l'aperçu) devient la
référence de tous les offsets. La relecture ne sert plus qu'à bring les pages,
et ces pages sont **alignées sur le texte stocké**
(`align_page_spans()` : chaque page est retrouvée verbatim dans le texte ; une
page introuvable n'est pas inventée, la page devient une estimation). Aucun
chemin ne construit plus un fait sur un texte que la personne n'a pas vu.

### D8 — La preuve d'une date désignait toute l'entrée 🔴

**Reproduit** : le fait de date reprenait les offsets de l'entrée complète.
Pour « 2023-2025 | Analyste financier | Groupe Synthetique », la citation
était l'entrée entière (125 caractères) : la date n'était plus désignée, et la
mission exige explicitement que *chaque date* garde sa source.

**Correction** : `_raw_date_span()` retrouve la date **brute** dans le passage
(`2023-2025`, et non `2023 – 2025` qui n'existe pas dans le document) et les
offsets du fait de date désignent **la date elle-même**. Le libellé affiché
reste normalisé, la preuve ne l'est jamais.

### D9 — Une phrase de résumé pouvait voler une rubrique entière 🔴

**Reproduit** : le moteur de structure de Mission 01 ancre une rubrique sur la
première ligne qui *contient* le mot-clé. Un CV courant contient une phrase de
profil comme « Compétences clés recherchées » : la rubrique Compétences
s'ancrait alors sur cette phrase, et **toutes les compétences réelles
disparaissaient de la relecture**.

```
PROFIL
Compétences clés recherchées   ← ancre de la rubrique « Compétences »

Compétences
Excel, SQL                      ← plus aucun fait proposé pour ces compétences

Langues
Anglais - C1
```

Constat mesuré sur le code livré : `labels == {'Anglais'}` — les compétences
`Excel` et `SQL` n'étaient **plus proposées à la personne**.

**Correction** : le builder lit désormais les rubriques sur des **en-têtes
stricts** — une ligne dont le texte normalisé *est* un mot-clé de rubrique. Une
ligne qui mentionne une rubrique n'appartient à aucune rubrique et ne devient
jamais un fait. Une rubrique au titre inhabituel (« Mes projets ») conserve le
bloc approximatif de Mission 01, à condition qu'il ne recouvre pas une
rubrique stricte.

### D10 — Un fait long écartait les faits courts qui tenaient 🟠

**Reproduit** : la boucle de bornage d'un champ de profil s'arrêtait au premier
élément qui ne tenait pas (`break`). Un fait de 80 caractères pouvait ainsi
empêcher un fait de 20 caractères qui tenait encore d'être proposé au profil.

**Correction** : les lignes écrites par la personne ne sont **jamais**
effacées, et chaque fait qui tient encore dans le champ est conservé.

### D11 — Coller un second CV effaçait la relecture du premier 🟠

**Reproduit** : le remplacement des propositions en attente se faisait sur le
**nom** du document. L'interface envoie toujours le nom « texte-profil » : deux
collages différents partageaient donc la même clé, et le second effaçait
silencieusement la relecture en cours du premier.

**Correction** : une **clé de source** (`candidate_facts.source_key`, schéma
v11) identifie le document *instance* : `import:<id>` pour un import,
`text:<empreinte du nom + du texte>` pour un collage. Relire le même document
remplace ses propres propositions ; deux documents différents ne s'effacent
jamais. Les faits déjà décidés ne sont jamais touchés.

### D12 — Une citation longue n'était plus le passage source 🟡

**Reproduit** : au-delà de 400 caractères, la citation était tronquée et
suffixée d'une ellipse — elle n'était donc plus `source[start:end]`, contrairement
à ce qu'affirme le rapport. Un fait à la longue description (en-tête de
200 caractères + résultat de 200 caractères) produisait un passage de 401
caractères, donc une citation falsifiée.

**Correction** : c'est le **passage** qui est borné (600 caractères, coupé à une
limite de mot), et non la citation après coup. La citation est désormais
**toujours** `source[start:end]`, y compris pour les faits longs.

---

## 3. Fichiers

### Créés (livraison reprise)

| Fichier | Rôle |
|---------|------|
| `career/candidate_profile.py` | Modèle : `Fact`, `Evidence`, `CandidateProfile`, 5 statuts, transitions, acteur, fusion profil, export portable |
| `career/profile_builder.py` | Pipeline : texte extrait → faits proposés (réutilise `career.cv_quality`) |
| `career_static/js/profile-builder.js` | UI d'approbation champ par champ |
| `scripts/candidate_profile_manual_check.py` | Essai manuel hors dépôt : lit un vrai CV, n'approuve rien, refuse un fichier du dépôt |
| `tests/test_candidate_profile.py` | 58 tests (modèle, builder, service, HTTP, garde-fous UI, script manuel, campagne adversariale n°1) |
| `tests/test_candidate_profile_adversarial.py` | **21 tests** — campagne adversariale n°2 (offsets sur l'aperçu, preuve des dates, rubriques, bornes de champ, collisions de documents, citation verbatim, migration v11) — *campagne n°2* |
| `tests/fixtures/candidate_profile/cv_synthetique.txt` | Fixture synthétique (CV complet) |
| `tests/fixtures/candidate_profile/cv_ocr_synthetique.txt` | Fixture synthétique (lecture OCR plate) |
| `tests/fixtures/candidate_profile/expected_facts.json` | Faits attendus du CV synthétique (golden file) |
| `docs/agent-reports/SPEC-SK10-CANDIDATE_PROFILE.md` | Ce rapport |

### Modifiés

| Fichier | Modification |
|---------|--------------|
| `career/service.py` | Table `candidate_facts` (schéma v9 → **v10** : `applied_field`, `applied_line` → **v11** : `source_key`), apply réversible, contacts persistés, migration qui répare les profils construits avant v10, export multi-documents, filtre de statut valide — **campagne n°2** : la lecture stockée devient la référence des offsets, les pages sont alignées sur ce texte, le remplacement des propositions en attente est borné à la clé de source |
| `career/candidate_profile.py` | `profile_target()`, `remove_profile_line()`, `merge_usable_facts_with_sources()` (savoir ce que chaque fait a réellement écrit) — **campagne n°2** : la borne de champ ne jette plus un fait qui tient et n'efface jamais une ligne écrite à la main |
| `career/profile_builder.py` | Offsets exacts sur le texte brut, citation verbatim, bornage par rubrique qui saute au lieu d'interrompre, confiance de page explicite — **campagne n°2** : rubriques à en-têtes stricts, `align_page_spans()`, `_raw_date_span()`, passage borné (citation toujours verbatim) |
| `career/router.py` | 7 endpoints profil candidat + payloads Pydantic |
| `career/cv_quality/parser.py` | `extract_pages_from_bytes()` : le texte par page (offsets → page exacte) |
| `career/cv_quality/__init__.py` | Export de `extract_pages_from_bytes` |
| `career_static/js/profile-builder.js` | « Corriger » disponible pour un fait approuvé ou corrigé |
| `career_static/index.html` | Panneau « Mon profil accepté, fait par fait » + chargement du script |
| `career_static/career.js` | Rafraîchissement du panneau à l'ouverture de l'onglet « Mon profil » |
| `career_static/career.css` | Styles des cartes de faits, compteurs, badges de statut |
| `tests/test_qualification_snapshot_persistence.py` | Version de schéma attendue : 9 → 10 → **11** |

---

## 4. Modèle de données

### Statuts par fait

| Statut | Sémantique | Utilisable pour le matching ? |
|--------|------------|--------------------------------|
| `proposed` | Extrait automatiquement, en attente de validation | **Non** |
| `approved` | Validé par la personne | **Oui** |
| `rejected` | Rejeté par la personne (erreur OCR, hors sujet) | **Non** |
| `modified` | Corrigé par la personne (date, niveau de langue, libellé) | **Oui** |
| `suspended` | Mis de côté temporairement | **Non** |

`USABLE_STATUSES = {approved, modified}` — c'est la seule porte d'entrée vers
le matching et les brouillons de candidature.

### Preuve d'un fait

```python
@dataclass(frozen=True)
class Evidence:
    source: str          # embedded_text | ocr | manual
    page: int            # 1-based, 0 = inconnue
    page_confidence: str # exact | estimated | unknown
    start_offset: int    # index du premier caractère dans le texte source
    end_offset: int      # index du dernier caractère (exclu)
    quote: str           # passage verbatim
    filename: str
```

La citation est le texte source **au caractère près** : `source[start:end]` donne
exactement la citation, espaces compris. Le test
`test_every_proposed_fact_points_at_its_own_source_passage` le vérifie pour
chaque fait proposé, et `test_the_quote_is_the_verbatim_source_passage` le
vérifie sur un document qui contient des espaces répétés.

> **Campagne n°2** : c'est désormais vrai **pour tous les faits**, y compris
> les plus longs. Le passage est borné à la construction (600 caractères, coupé
> à une limite de mot) et la citation n'est plus tronquée après coup. Le test
> `test_the_quote_of_a_long_fact_is_still_the_verbatim_source_passage` verrouille
> ce point.

### Origine des pages

| Situation | Page | Confiance |
|-----------|------|-----------|
| PDF lu par le parser Mission 01 | page réelle | `exact` |
| TXT avec sauts de page (`\f`) | page réelle | `exact` |
| DOCX (aucune information de page) | bloc unique | `estimated` |
| Lecture OCR (texte aplati, `ocr_pages` connu) | répartition estimation | `estimated` |
| Texte collé | page 1 | `estimated` |

L'interface affiche la mention « (estimée) » quand la page n'est pas certaine :
une page estimée est une indication, jamais une preuve.

> **Campagne n°2** : la page n'est plus déduite d'une jointure supposée. Les
> pages sont **alignées sur le texte réellement montré** : chaque page est
> retrouvée verbatim dans le texte de l'aperçu. Une page introuvable n'est pas
> inventée — la page devient alors une estimation, et l'interface le dit.

---

## 5. Pipeline

### 5.1 Extraction

**La lecture stockée avec l'import est la référence de tous les offsets.** C'est
elle que la personne a vue dans l'aperçu ; c'est donc elle que les offsets
désignent.

`career/cv_quality/parser.py::extract_pages_from_bytes()` renvoie la liste des
textes de page. Ces pages ne sont **pas** ré-jointees pour construire le texte
des faits : elles sont **alignées** sur le texte stocké
(`career/profile_builder.py::align_page_spans()`), ce qui rend chaque offset
vérifiable dans l'aperçu, y compris sur un PDF de plusieurs pages (dont la
lecture stockée et la relecture ne joignent pas les pages de la même façon).

Quand la source est un import OCR, le service réutilise le texte OCR déjà
stocké (l'OCR aplatit les pages) et répartit le texte sur `ocr_pages` en mode
`estimated`. La lecture proposée est **exactement celle que la personne a vue**
dans l'aperçu de l'import.

### 5.2 Propositions

`career/profile_builder.py::build_fact_proposals()` :

1. Les rubriques `Expérience`, `Formation`, `Compétences`, `Langues`, `Projets`,
   `Certifications` sont lues sur des **en-têtes stricts** : une ligne dont le
   texte normalisé *est* un mot-clé de rubrique. Une rubrique approximative de
   Mission 01 n'est reprise que si aucune rubrique stricte ne la couvre.
2. Chaque rubrique est découpée en items (une ligne, ou une virgule pour les
   compétences). Les offsets sont calculés sur le texte **brut** : le passage
   `source[start:end]` est toujours l'item lui-même.
3. Les expériences sont lues ligne par ligne : une ligne datée ouvre une
   entrée (`rôle | société | dates`), les lignes suivantes portent le
   résultat. Ce parsing est local et déterministe — le moteur de structure de
   Mission 01 est réutilisé pour les rubriques, mais sa récupération
   « Canva » (heuristique de reprise) est écartée ici parce qu'elle ne donne
   pas d'offsets fiables.
4. Les **dates** sont des faits à part entière : leurs offsets désignent la
   date brute dans le document (`2023-2025`), pas l'entrée qui la contient.
5. Chaque fait est créé avec `status="proposed"`, sa preuve et sa page.

Garde-fou structurel : `build_fact_proposals()` lève une exception si un fait
sortait avec un statut autre que `proposed`, et l'insertion SQL du service
écrit le littéral `'proposed'` — **aucun chemin de code n'approuve un fait**.

### 5.3 Décision

| Décision API | Effet |
|--------------|-------|
| `approve` | `approved` — le fait devient utilisable |
| `reject` | `rejected` — le fait est écarté |
| `suspend` | `suspended` — le fait est mis de côté, sans être perdu |
| `modify` | `modified` — le fait est corrigé (valeur obligatoire) |
| `reopen` | `proposed` — le fait revient en relecture |

La machine à états est explicite (`ALLOWED_TRANSITIONS`) : un fait rejeté ou
mis de côté doit être **rouvert** avant de pouvoir être approuvé à nouveau.
`apply_decision()` exige aussi `actor="user"` : aucun chemin automatisé ne peut
statuer sur un fait, et un fait lu par OCR attend donc toujours une décision
humaine.

Une correction remplace le **niveau** quand le fait a une valeur structurée
(niveau de langue) et le **libellé** sinon ; la valeur d'origine est conservée
dans `original_label` / `original_value` pour l'audit.

### 5.4 Profil actif

`merge_usable_facts()` ajoute au profil local **uniquement** les faits
approuvés ou corrigés, sans doublon et dans la limite de chaque champ. Les
faits de contact (`contact_email`, `contact_phone`) complètent un champ vide,
jamais un champ déjà rempli. Le service l'applique à deux endroits :

- `_scoring_context()` → la correspondance (score, couverture, gaps) ;
- `_application_context()` → le brouillon de CV / lettre et le kit de
  candidature.

`merge_usable_facts_with_sources()` retourne en plus **ce que chaque fait a
réellement écrit** : c'est ce qui rend l'« apply » réversible (D1). Une ligne
que la personne avait écrite elle-même n'est jamais attribuée à un fait, donc
jamais retirée par une décision.

Un fait `proposed`, `rejected` ou `suspended` ne peut donc **jamais** justifier
une candidature : il n'entre dans aucun de ces deux chemins, et la ligne qu'il
avait éventuellement écrite dans le profil lui est retirée.

---

## 6. API

| Méthode | Route | Rôle |
|---------|-------|------|
| `GET` | `/api/career/candidate-profile/facts?status=` | Liste des faits + compteurs par statut (statut inconnu → 400) |
| `POST` | `/api/career/candidate-profile/proposals` | Propose les faits d'un import (`import_id`) ou d'un texte collé |
| `PATCH` | `/api/career/candidate-profile/facts/{fact_id}` | Une décision explicite (`decision`, `value`, `note`) |
| `DELETE` | `/api/career/candidate-profile/facts/{fact_id}` | Supprime un fait, sa preuve et sa ligne de profil |
| `GET` | `/api/career/candidate-profile/active` | Profil actif : seuls les faits utilisables + leurs preuves |
| `POST` | `/api/career/candidate-profile/apply` | Applique les faits approuvés aux champs du profil |
| `GET` | `/api/career/candidate-profile/export` | Export portable JSON (tous les faits, statut et preuve) |

L'export reprend le schéma `come-ai-candidate-profile/1` :

```json
{
  "schema": "come-ai-candidate-profile/1",
  "counts": {"proposed": 12, "approved": 4, "rejected": 1, "modified": 0, "suspended": 0},
  "source_documents": ["cv-synthetique.txt"],
  "facts": [
    {
      "id": "fact_…", "kind": "skill", "label": "Excel", "status": "approved",
      "evidence": {"source": "embedded_text", "page": 1, "page_confidence": "exact",
                   "start_offset": 428, "end_offset": 433, "quote": "Excel",
                   "filename": "cv-synthetique.txt"}
    }
  ],
  "active_profile": {"skills": ["Excel"]}
}
```

`source_documents` liste **tous** les documents d'origine : un export ne
prétend jamais venir d'un seul document.

La capability `GET /api/career/health` expose désormais `candidate_profile` :
`local_only: true`, `field_by_field_review: true`, `ocr_auto_approved: false`,
`portable_export: true`, et les 5 statuts.

---

## 7. Critères non négociables → preuves

| # | Critère | Comment il est garanti | Test |
|---|---------|-------------------------|------|
| 1 | **Résultat OCR jamais automatiquement approuvé** | L'insertion SQL écrit le littéral `'proposed'` ; le builder refuse de produire un autre statut ; `apply_decision()` exige `actor="user"` ; seule la décision explicite change un statut | `test_builder_never_approves_anything_even_for_ocr`, `test_an_ocr_import_proposes_facts_without_approving_them`, `test_service_never_writes_an_approved_status_outside_a_decision`, `test_only_the_person_can_decide_a_fact` |
| 2 | **Chaque compétence, expérience, date, diplôme garde sa source** | `Evidence` (page + offsets + citation) est obligatoire et sérialisée ; la citation **est** `source[start:end]`, sans normalisation cachée ; **les offsets désignent le texte montré dans l'aperçu** ; une date désigne la date | `test_builder_keeps_the_exact_source_of_every_fact`, `test_every_proposed_fact_points_at_its_own_source_passage`, `test_the_quote_is_the_verbatim_source_passage`, `test_builder_maps_offsets_to_the_right_page_when_pages_are_known`, `test_a_docx_import_never_claims_an_exact_page`, `test_the_offsets_point_into_the_text_shown_in_the_import_preview`, `test_a_multi_page_pdf_keeps_the_offsets_of_the_preview_text`, `test_a_date_fact_points_at_the_date_itself`, `test_the_quote_of_a_long_fact_is_still_the_verbatim_source_passage` |
| 3 | **Suppression et export fonctionnent** | `DELETE` sur un fait (avec retrait de sa ligne de profil), export JSON portable, export global de Données perso, reset local | `test_service_deletes_one_fact`, `test_a_deleted_fact_leaves_the_profile_it_had_been_applied_to`, `test_service_exports_a_portable_profile`, `test_the_export_lists_every_source_document`, `test_http_export_returns_a_local_json_file`, `test_the_local_reset_erases_the_facts` |
| 4 | **Aucun document réel dans les tests** | Trois fixtures 100 % synthétiques + golden file ; aucun fichier de l'utilisateur ; le PDF de test est fabriqué à la volée | `tests/fixtures/candidate_profile/*` |
| 5 | **Faits non approuvés ≠ justifier une candidature** | `merge_usable_facts()` ne retient que `approved` / `modified` ; l'apply est **réversible** : un fait rejeté, mis de côté, rouvert ou supprimé perd sa ligne de profil | `test_a_proposed_fact_never_reaches_the_candidature_draft`, `test_a_rejected_fact_leaves_the_profile_it_had_been_applied_to`, `test_a_suspended_fact_leaves_the_profile_it_had_been_applied_to`, `test_a_reopened_fact_leaves_the_profile_it_had_been_applied_to`, `test_a_deleted_fact_leaves_the_profile_it_had_been_applied_to`, `test_the_manual_profile_value_is_never_removed_by_a_fact_decision`, `test_a_shared_line_leaves_the_profile_only_with_the_fact_that_justifies_it`, `test_only_approved_facts_reach_the_profile_fields` |
| 6 | **Vrais essais utilisateur séparés des fixtures Git** | Script manuel qui lit un document **hors du dépôt** et refuse un fichier du dépôt ; procédure d'essai en section 9 ; **essai réel contre un serveur uvicorn** (section 9 bis) | `test_the_manual_check_script_refuses_a_document_stored_in_the_repository`, `test_the_manual_check_script_reads_a_document_outside_the_repository` |

Les 5 statuts sont implémentés et testés un par un
(`test_five_statuses_are_declared_and_only_two_are_usable`,
`test_apply_decision_covers_every_status`).

La migration **v9 → v10** répare les profils construits par la version
précédente : la ligne d'un fait qui n'est plus approuvé est retirée du profil
(`test_the_migration_repairs_a_profile_built_before_the_reversible_apply`).

La migration **v10 → v11** (campagne n°2) ajoute la clé de source sans
réécrire aucun fait décidé
(`test_the_migration_to_v11_keeps_the_existing_facts`,
`test_the_migration_to_v11_adds_the_source_key`).

---

## 8. Interface

Panneau **« Mon profil accepté, fait par fait »** dans l'onglet « Mon profil » :

- sélection d'un import local (liste alimentée par `/api/career/profile-imports`)
  ou collage d'un texte ;
- compteur par statut (à vérifier / approuvés / corrigés / mis de côté /
  rejetés) ;
- une carte par fait : type, statut, badge « OCR — validation obligatoire » si
  lecture OCR, page + caractères, citation verbatim ;
- actions : **Approuver**, **Corriger** (champ de saisie), **Rejeter**,
  **Mettre de côté** ; pour un fait déjà décidé : **Corriger**, **Mettre de
  côté**, **Rouvrir**, **Supprimer** ;
- bouton « Appliquer les faits approuvés à mon profil » ;
- bouton « Exporter mon profil » (télécharge le JSON portable).

Le rendu passe par `textContent` uniquement : aucun contenu de document n'est
injecté en HTML (`test_the_profile_panel_exposes_a_field_by_field_review`).

Règle affichée dans l'interface : « Rien n'est validé automatiquement, y compris
ce qui vient de l'OCR. Un fait proposé, rejeté ou mis de côté ne peut pas
justifier une correspondance ni une candidature. »

---

## 9. Essais utilisateur réels (hors dépôt)

Ces essais se font **avec le CV de la personne**, sur la machine locale. Aucun
CV réel n'entre dans Git : les fixtures du dépôt restent synthétiques.

**Outil hors dépôt** — `scripts/candidate_profile_manual_check.py` lit un
document réel *hors du dépôt*, affiche les faits proposés avec page, offsets et
citation, et **refuse** un fichier situé dans le dépôt :

```bash
cp ~/Documents/mon-cv.pdf /tmp/mon-cv.pdf      # hors du dépôt
python scripts/candidate_profile_manual_check.py /tmp/mon-cv.pdf
```

Le script n'écrit rien, n'envoie rien et n'approuve aucun fait.

**Dans l'application** (sur le CV de la personne) :

1. **Import** — dans « Mon profil », importer un vrai PDF (texte) et un vrai PDF
   scanné. Vérifier que le second déclenche l'OCR macOS et affiche le badge
   « OCR — validation obligatoire ».
2. **Propositions** — « Proposer des faits à vérifier » depuis l'import. Vérifier
   que chaque carte montre la page et une citation qui correspondent au PDF
   ouvert à côté.
3. **Approbation** — approuver une compétence, corriger une date d'expérience,
   rejeter une ligne d'OCR fausse, mettre une certification de côté.
4. **Effet matching** — ouvrir une offre : la compétence approuvée doit
   apparaître dans la couverture ; la compétence rejetée ne doit apparaître
   nulle part.
5. **Effet candidature** — préparer un brouillon : la section « Compétences »
   contient uniquement les faits approuvés.
6. **Retour arrière** — approuver une compétence, l'appliquer au profil, puis la
   **rejeter** : elle doit disparaître du profil *et* du brouillon. C'est le
   scénario que la version précédente ne tenait pas.
7. **Suppression** — supprimer un fait : il disparaît de la liste et du profil.
8. **Export** — exporter le profil, rouvrir le JSON, vérifier que chaque fait
   garde page + offsets + citation.
9. **Reprise** — redémarrer l'application : les faits, leurs statuts et leurs
   preuves sont toujours là.

Retour à consigner hors dépôt : `docs/agent-reports/SPEC-SK10-ESSAIS-<date>.md`
(ne pas versionner un document personnel).

### Essai réel exécuté par le worker (serveur local réel)

Pour ne pas laisser la vérification au seul niveau des tests, le panneau a été
exercé contre un **vrai serveur `uvicorn`** (répertoire de données hors dépôt,
CV synthétique, aucun document réel, aucun envoi externe) :

| Étape | Requête | Résultat observé |
|-------|---------|------------------|
| Propositions | `POST /api/career/candidate-profile/proposals` | HTTP 201 — 17 faits, tous `proposed`, compteurs `{proposed: 17}` |
| Preuve | — | fait « Power BI » : offsets 453–461, citation `Power BI` |
| Approbation | `PATCH …/facts/{id}` `{"decision":"approve"}` | HTTP 200 — `approved`, `usable: true` |
| Application | `POST …/apply` | HTTP 200 — appliqués 1, écrits 1, ignorés 0 — `skills: "Power BI"` |
| Rejet | `PATCH …/facts/{id}` `{"decision":"reject"}` | HTTP 200 — `rejected` |
| **Profil après rejet** | `GET /api/career/profile` | **`skills: ""`** — le fait rejeté ne justifie plus rien (défaut D1 corrigé) |
| Profil actif | `GET …/candidate-profile/active` | 0 fait utilisable, 16 en attente |
| Export | `GET …/candidate-profile/export` | `come-ai-candidate-profile/1`, `source_documents: ["cv-hors-depot.txt"]` |
| Interface | `GET /career`, `GET /career-static/js/profile-builder.js` | HTTP 200 — panneau et script servis |
| Capacité | `GET /api/career/health` | `local_only: true`, `ocr_auto_approved: false`, les 5 statuts |

Avant la correction D1, l'étape « Profil après rejet » renvoyait
`skills: "Power BI"` : le fait rejeté continuait de justifier une candidature.

### Essai réel exécuté par la campagne n°2 (serveur local réel)

Même protocole, contre un **vrai serveur `uvicorn`** (répertoire de données
hors dépôt, CV synthétique, aucun document réel, aucun envoi externe). L'essai
porte cette fois sur la **preuve** : chaque offset est vérifié **dans l'aperçu
de l'import**, caractère par caractère.

| Étape | Requête | Résultat observé |
|-------|---------|------------------|
| Import | `POST /api/career/profile-imports` | HTTP 200 — `extraction_method: embedded_text`, aperçu de 369 caractères |
| Propositions | `POST …/candidate-profile/proposals` | HTTP 201 — 12 faits, tous `proposed`, `pages_known: true` |
| **Preuve** | — | **les 12 faits vérifiés dans l'aperçu** : `aperçu[start:end] == quote` pour chacun, page `exact` |
| Preuve d'une date | — | fait « 2023 – 2025 » : offsets **75–84**, citation `2023-2025` (et non plus l'entrée de 125 caractères) |
| Approbation | `PATCH …/facts/{id}` `{"decision":"approve"}` | HTTP 200 — `approved`, `usable: true` |
| Application | `POST …/apply` | HTTP 200 — appliqués 1, écrits 1, ignorés 0 — `skills: "Excel"` |
| Rejet | `PATCH …/facts/{id}` `{"decision":"reject"}` | HTTP 200 — `rejected`, `usable: false` |
| **Profil après rejet** | `GET /api/career/profile` | **`skills: ""`** — le fait rejeté ne justifie plus rien |
| Export | `GET …/candidate-profile/export` | HTTP 200 — `come-ai-candidate-profile/1`, `source_documents: ["cv_synthetique.txt"]` |
| **Deux collages** | `POST …/proposals` ×2 | les deux relectures **survivent** : `Power BI`, `Tableau` **et** `Espagnol` présents (défaut D11 corrigé) |
| Interface | `GET /career`, `GET /career-static/js/profile-builder.js` | HTTP 200 — panneau et script servis |
| Capacité | `GET /api/career/health` | `local_only: true`, `ocr_auto_approved: false`, les 5 statuts |

Sortie de la vérification des offsets (12 faits, tous conformes) :

```
  OK  contact      E-mail                    p1 exact   16-44   'camille.exemple@example.test'
  OK  contact      Téléphone                 p1 exact   45-62   '+33 6 12 34 56 78'
  OK  experience   Analyste financier        p1 exact   75-200  '2023-2025 | Analyste financier | Gro'
  OK  date         2023 – 2025               p1 exact   75-84   '2023-2025'
  OK  education    2021-2023 | Master …      p1 exact  212-276  "2021-2023 | Master Finance d'entrepr"
  OK  date         2021 – 2023               p1 exact  212-221  '2021-2023'
  OK  skill        Excel                     p1 exact  290-295  'Excel'
  OK  skill        Power BI                  p1 exact  297-305  'Power BI'
  OK  skill        SQL                       p1 exact  307-310  'SQL'
  OK  skill        analyse financiere        p1 exact  312-330  'analyse financiere'
  OK  language     Francais                  p1 exact  340-356  'Francais - natif'
  OK  language     Anglais                   p1 exact  357-369  'Anglais - C1'
```

---

## 10. Validation

```bash
./checklist_codex.sh                                   # → TOUT VERT
.venv/bin/python -m pytest -q tests/test_candidate_profile.py               # 58 passed
.venv/bin/python -m pytest -q tests/test_candidate_profile_adversarial.py  # 21 passed
.venv/bin/python -m pytest -q                           # 1503 passed, 1 skipped
.venv/bin/python -m ruff check .                       # All checks passed
git diff --check                                       # propre
```

Détail de la suite : 39 tests de la livraison reprise + **19 tests adversariaux
(campagne n°1)** — apply réversible (6), contacts appliqués (2), honnêteté du
résultat d'apply (1), migration v10 (1), filtre de statut (1), export
multi-documents (1), provenance verbatim (2), bornage par rubrique (1), ligne
partagée (1), confiance de page (2), interface (1) — + **21 tests adversariaux
(campagne n°2)** — offsets sur l'aperçu (3 : TXT, DOCX, PDF multipage), preuve
des dates (2), rubriques stricts (3), borne de champ (1), collision de
documents (2), citation verbatim (2), migration v11 (2), profil manuel jamais
perdu (1), robustesse des décisions (2), OCR et page (2).

**Preuve de la reproduction** : sur le code livré (`git stash` des
corrections), **10 des 21 tests de la campagne n°2 échouent** ; ils passent
tous après correction. Les 10 échecs portent sur D7 (offsets : aperçu TXT,
PDF multipage), D8 (dates), D9 (rubriques strictes et titre inhabituel), D10
(borne de champ), D11 (collision de documents) et la clé de source de la v11.

---

## 11. Limites connues et suite

- **La page d'un import PDF** dépend de la relecture Mission 01 : le service
  ré-extrait le document stocké avec le parser local. *Campagne n°2 : les
  **offsets** ne dépendent plus de cette relecture — ils désignent toujours le
  texte de l'aperçu (D7). Seule la **page** dépend encore de la relecture :
  quand une page n'est pas retrouvée verbatim dans le texte de l'aperçu, la
  page devient une estimation et l'interface le signale (« (estimée) »).*
- **Un PDF scanné** ne peut pas être re-lu par le parser : le service réutilise
  alors le texte OCR stocké, avec des pages estimées et une validation
  obligatoire.
- **Un titre de rubrique inhabituel** (« Mes projets ») reste reconnu par
  l'approximation de Mission 01, dont les offsets peuvent être moins exacts que
  ceux d'un titre strict. Un titre strict est toujours prioritaire.
- **Supprimer un import** ne supprime pas les faits déjà proposés : leurs
  citations restent dans le profil. C'est un choix — une décision explicite ne
  disparaît pas en silence. Les faits restent supprimables un par un.
- **Une ligne écrite à la main** qui ressemble exactement à un fait approuvé
  reste la ligne de la personne : aucune décision ne la retire.
- **SK-11 (suite)** : le profil actif est prêt à alimenter la correspondance
  fine et la justification de candidature. Le verrou posé ici (un fait non
  approuvé ne justifie rien, même après avoir été appliqué) est la condition
  d'entrée de SK-11.
- **Extensions possibles** : comparaison de deux versions d'un même CV, export
  PDF du profil portable, détection de faits contradictoires entre deux
  documents, ré-import d'un profil portable.

---

**Rapport généré le** : 2026-10-22 (campagne n°2 — le corps du rapport, §0 à §9
bis et §10, décrit la campagne n°1 reprise telle quelle ; §2 bis décrit la
campagne n°2)
**Agent** : Mission CVBOOST-31 — SK-10 (worker `cvboost-31-1792623192`)
**Statut** : ✅ Complet, audité et corrigé, prêt pour relecture et intégration
