# Career — extension légale et mesurée des sources internationales (vague 3)

Mission CVBOOST-06, 20 octobre 2026. Deux connecteurs seulement, choisis après
audit du registre et démonstration réseau réelle bornée. Aucun agrégateur,
aucune URL codée dans le service : les identifiants vivent dans le registre
vérifié, les URLs officielles restent dérivées de chaque source vérifiée.

## Décision d'audit (ce qui a été retenu et pourquoi)

| Candidat | Documentation officielle | Démonstration réseau | Décision |
|---|---|---|---|
| **Recruitee** (nouveau connecteur) | Oui — «The public API doesn't require any authentication» (support recruiting officiel, article 1066286) | Oui — feed réel bunq, 200 en ~0.2 s (gzip) | **Intégré** |
| **SmartRecruiters** (supporté, jamais démontré) | Oui — posting API publique, `destination=PUBLIC` | Oui — 365 offres brutes sur le board Experian | **Première source réelle ajoutée au registre** |
| Workable | Partiellement — endpoint widget documenté via un redirect (302) vers `apply.workable.com` | Oui techniquement, mais aucune entreprise finance dont la page carrière officielle démontre le lien (Arena/CCaventus: site sans page carrière accessible; banks testées: 0 offre publique) | **Resté dehors — non démontrable** |
| JSON-LD générique (schema.org) | — | Non nécessaire pour cette vague | Reporté |

Une source non démontrable reste désactivée : aucun connecteur Workable,
aucune entrée Personio/Teamtailor/JSON-LD non démontrée n'a été ajoutée.

## Ce qui est livré

1. `RecruiteeConnector` (`career/connectors/public_ats.py`) — connecteur isolé,
   transport et horloge injectables ; HTTPS uniquement ; hôtes limités aux
   sous-domaines `*.recruitee.com` ; redirects refusés ; timeout, plafond de
   taille (8 MiB lu **et** décompressé), 1 requête documentée par source ;
   User-Agent identifié ; un seul flux par source, du JSON publié uniquement
   (`status = published`).
2. Transport public-ATS unique : envoi `Accept-Encoding: gzip` et
   décompression bornée par le même plafond. Mesuré : le CDN Recruitee
   bloque les grandes réponses non compressées (stall > 8 s) et répond en
   ~0.2 s compressé ; les connecteurs existants gardent leurs plafonds.
3. Registre : 21 → 23 sources vérifiées.
   - `registry:recruitee:bunq` — banque néerlandaise ; page carrière officielle
     `careers.bunq.com` (bunq.com/careers y redirige) ; provenance vérifiée
     2026-10-20 ; conditions documentées dans l'entrée.
   - `registry:smartrecruiters:experian` — première source SmartRecruiters ;
     `jobs.experian.com` (site officiel) référence le board public
     `jobs.smartrecruiters.com/Experian`.
4. `CONNECTOR_SPECS` documente désormais les **conditions connues** de chaque
   fournisseur (sans clé, pagination bornée, snapshot temporel) — testé.
5. Fixtures hors ligne `recruitee` + batterie de tests : désactivation par
   défaut, hôte invalide refusé, liste de publication par source (hôte
   vérifié OU sous-domaine locataire seulement), offre archivée jamais
   importée, fallback URL locataire jamais détourné, décompression gzip
   bornée, flux tronqué jugé invalide.

## Rendement mesuré (contrôle réseau réel borné, 2026-10-20)

Aucun profil ni CV, aucune clé ni cookie ; stockage jetable.

| Source | Brutes | Valides | Stages confirmés | Retenues finance | Conformes | À vérifier | Doublons | Latence | Erreurs |
|---|---|---|---|---|---|---|---|---|---|
| bunq (Recruitee) | 20 | 20 | 0 | 2 | 0 | 2 | 0 | 3.46 s | 0 |
| Experian (SmartRecruiters) | 365 | 365 | 0 | 1 | 0 | 1 | 0 | 12.98 s | 0 |

Détail factuel minimal dans `LIVE_SOURCE_CHECK_2026-10-20_WAVE3.json`.

Lecture honnête : le choix concret ne passe pas de 21 à 23 sources et les
trois offres retenues de plus sont toutes « à vérifier » — faits contractuels
absents chez les deux fournisseurs. Le gain est structurel (première
démonstration SmartRecruiters, premier locataire Recruitee) et non une
multiplication des offres affichées.

## Défauts trouvés et corrigés pendant la mission

1. **Transfert bloqué par les CDNs sans encodage** : le feed Recruitee ne
   répondait pas dans le délai (8 s) en `identity`, et répond en <1 s
   compressé. Correctif transport : `Accept-Encoding: gzip` + décompression
   bornée (plafond 8 MiB réappliqué sur le corps décompressé ; flux tronqué
   ou annexe invalide refusé, jamais deviné).
2. **URL de liste Recruitee** : les sous-domaines locataires bloquent les
   routes de page hors API. L'URL retenue est celle publiée par le feed
   (`careers_url`) **limitée à l'hôte du registre** ; toute autre hôte est
   remplacée par l'URL locataire dérivée du token enregistré — jamais
   propagée.
3. **Timeout transitoire SmartRecruiters** observé en refresh quasi
   consécutif du même board (délai par requête), récupéré en run isolé.
   Noté comme variance mesurée ; le refresh applicatif reste borné par le
   budget réseau de 60 s et rejouable.

## Vérifications exécutées

- Tests ciblés connectors + registre : 33 vert.
- Non-régression : `1379 passed in 203 s` sur l'arbre complet.
- Contrôle réel borné des deux nouvelles sources (deux exécutions, une
  variance capturée puis récupérée), publié au format JSON réduit.

## Limites honnêtes

- Le flux Recruitee renvoie sa page par défaut (le vendeur ignore les
  paramètres de pagination) : 20 offres mesurées pour bunq. C'est écrit dans
  la doc du connecteur et testé.
- Un board Experian contient 365 annonces publiques : quatre pages paginées
  bornées à 400 lignes ; la latence dépend du CDN (~13 s mesurées).
- Une présence au registre ne promet ni stage, ni permanence de la source.
- Aucune candidature envoyée ; aucune donnée de profil lue.

## Retour arrière

Le lot est isolé sur `agent/cvboost-05` (commit dédié). Revenir au commit
précédent du lot restaure le registre de 21 sources, retire le connecteur
Recruitee et le support gzip sans toucher aux candidatures existantes.
