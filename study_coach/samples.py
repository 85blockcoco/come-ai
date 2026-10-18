"""Synthetic courses used by the demo and by the offline test-suite.

Everything here is invented for the exercise: no personal document, no real
company, no credential, no personal data.  The texts are intentionally small so
that the expected behaviour of the engine is readable.
"""

from __future__ import annotations

FINANCE_COURSE = """# Évaluation d'entreprise — cours synthétique

## 1. La valeur actuelle nette

La valeur actuelle nette (VAN) est la somme des flux de trésorerie futurs
actualisés moins l'investissement initial. Un projet dont la VAN est positive
augmente la valeur de l'entreprise.

VAN = somme des flux actualisés - investissement initial

Exemple : pour un investissement initial de 100 000 € et des flux actualisés de
40 000 €, la VAN vaut -60 000 €.

## 2. Le coût moyen pondéré du capital

Le coût moyen pondéré du capital (CMPC) est le coût moyen du financement de
l'entreprise. Il combine le coût de la dette et le coût des fonds propres.

CMPC = part dette x cout de la dette x (1 - taux d'IS) + part fonds propres x cout des fonds propres

## 3. Les flux de trésorerie disponibles

Le flux de trésorerie disponible (FCFF) est le flux de trésorerie généré par
l'activité, indépendamment du financement de l'entreprise.

FCFF = résultat d'exploitation x (1 - taux d'IS) + amortissements - variation du BFR - investissements

Dans notre exemple, le coût de la dette vaut 6 % et le taux d'IS vaut 25 %.

## 4. Les ratios de rentabilité

Le ratio de rentabilité désigne le rapport entre le résultat net et le chiffre
d'affaires. Le ratio de liquidité désigne la capacité d'une entreprise à
honorer ses dettes à court terme.

## 5. Les limites de la méthode

Cette méthode suppose que les flux de trésorerie sont parfaitement prévisibles,
ce qui n'est pas réaliste en pratique.
"""

ACCOUNTING_COURSE = """# Comptabilité générale — cours synthétique

## 1. Les principes comptables

La comptabilité repose sur le principe de la partie double : chaque opération
se traduit par au moins deux écritures de montant identique.

L/amortissement linéaire est une méthode qui répartit la valeur d'un immobilisation
sur sa durée d'utilisation. Le plan d'amortissement est la table qui indique
le montant annuel à comptabiliser.

Amortissement annuel = (valeur d'acquisition - valeur résiduelle) / durée d'utilisation

## 2. Le bilan

Le bilan est l'état patrimonial de l'entreprise à une date donnée. Il présente
l'actif et le passif. L'actif est l'ensemble des biens et des créances.

## 3. Le compte de résultat

Le compte de résultat est un état de performance qui présente les charges et
les produits de l'exercice. Le résultat net est le solde du compte de résultat.

## 4. Le cas des provisions

Une provision est une retenue d'un montant destiné à couvrir une charge
probable et non certaine.
"""

MATH_COURSE = """# Mathématiques financières — cours synthétique

## 1. L'intérêt simple

L'intérêt simple est le coût d'un emprunt calculé sur le capital initial. Il ne
varie pas dans le temps.

Interet = capital x taux x duree

Exemple : un capital de 2 000 € placé à 3 % pendant 2 ans produit 120 € d'intérêts.

## 2. L'intérêt composé

L/intérêt composé reincorpore à chaque période les intérêts déjà perçus. Il
croît plus vite que l'intérêt simple.

## 3. L'annuité constante

Une annuité constante est une série de versements égaux. Le montant de
l'annuité dépend du taux et de la durée.
"""

# --------------------------------------------------------------------------- #
# Extended courses for pedagogical quality (P1)
# --------------------------------------------------------------------------- #

DCF_COURSE = """# DCF Valuation — cours synthétique

## 1. Principes de base de la méthode DCF

La méthode DCF (Discounted Cash Flow) estime la valeur d'un actif par la somme
actualisée de ses flux de trésorerie futurs. Elle repose sur trois piliers :
la projection des flux, le choix du taux d'actualisation, et la valeur terminale.

La valeur d'entreprise (Enterprise Value) vaut la somme des FCFF actualisés
plus la valeur terminale actualisée.

Enterprise Value = Σ FCFF_t / (1 + WACC)^t + TV / (1 + WACC)^n

## 2. Les flux de trésorerie disponibles (FCFF)

Le Free Cash Flow to Firm représente le cash généré par l'exploitation
disponible pour tous les financeurs (créanciers et actionnaires).

FCFF = EBIT × (1 - taux d'IS) + Amortissements - ΔBFR - CAPEX

Un FCFF positif signifie que l'entreprise génère du cash après avoir financé
son exploitation et ses investissements de maintien.

## 3. Le coût moyen pondéré du capital (WACC)

Le WACC est le taux d'actualisation des FCFF. Il reflète le coût de
financement moyen de l'entreprise, pondéré par la structure de capital.

WACC = E/(E+D) × Ke + D/(E+D) × Kd × (1 - taux d'IS)

Ke (coût des fonds propres) se calcule souvent par le CAPM :
Ke = taux sans risque + β × prime de risque de marché.

## 4. La valeur terminale

La valeur terminale capture la valeur au-delà de l'horizon de projection explicite.
Deux méthodes principales :

Méthode de Gordon-Shapiro (croissance perpétuelle) :
TV = FCFF_{n+1} / (WACC - g) avec g < WACC

Méthode des multiples de sortie :
TV = Multiple_EV/EBITDA × EBITDA_n

## 5. Passage de la valeur d'entreprise à la valeur des capitaux propres

Equity Value = Enterprise Value - Dette Nette + Trésorerie - Instruments hybrides
- Engagements hors bilan (locatif, retraites, etc.)

## 6. Sensibilité et limites

La VAN est très sensible au WACC et au taux de croissance terminal g.
Une variation de 1 % du WACC peut changer la valeur de 15 à 30 %.
Les hypothèses de croissance perpétuelle doivent rester réalistes (g ≈ inflation).

Exemple chiffré : FCFF an 1 = 50 M€, croissance 3 % pendant 5 ans, WACC = 9 %,
g terminal = 1.5 %. EV ≈ 850 M€.
"""

MARKET_FINANCE_COURSE = """# Finance de Marché — cours synthétique

## 1. Obligations : prix, rendement, duration

Le prix d'une obligation est la somme actualisée de ses coupons et du principal.

Prix = Σ Coupon / (1 + y)^t + Principal / (1 + y)^n

Le rendement actuariel (YTM) est le taux y qui égalise le prix de marché
aux flux actualisés.

La duration de Macaulay mesure la maturité moyenne pondérée des flux :
Duration = Σ t × PV(flux_t) / Prix

La duration modifiée approxime la sensibilité du prix au taux :
ΔPrix / Prix ≈ - Duration_modifiée × Δy

Convexité : correction du second ordre pour les grands mouvements de taux.

## 2. Actions : modèles d'évaluation

Modèle des dividendes actualisés (DDM) :
P0 = Σ Div_t / (1 + ke)^t + Pn / (1 + ke)^n

Modèle de Gordon (croissance constante) :
P0 = Div_1 / (ke - g) avec g < ke

Modèle des multiples : P/E, EV/EBITDA, P/BV. Utilisés en relatif (comparables).

## 3. Structure par terme des taux

Courbe des taux : relation entre taux zéro-coupon et maturité.
Théories : anticipation, prime de liquidité, segmentation des marchés.

Bootstrapping : construction de la courbe zéro-coupon à partir des instruments
de marché (dépôts, swaps, obligations).

Forward rates : taux implicites pour périodes futures.
f(t1, t2) = [(1 + z_t2)^t2 / (1 + z_t1)^t1]^(1/(t2-t1)) - 1

## 4. Dérivés de base

Option européenne (Black-Scholes) :
Call = S × N(d1) - K × e^(-rT) × N(d2)
d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
d2 = d1 - σ√T

Grecques : Delta, Gamma, Vega, Theta, Rho. Gestion des risques de portefeuille.

Swap de taux : échange fixe contre variable. Taux de swap = taux par du swap.

## 5. Gestion de portefeuille

Frontière efficiente (Markowitz) : maximiser E(r) pour une variance donnée.
Ratio de Sharpe = (E(r_p) - r_f) / σ_p

CAPM : E(r_i) = r_f + β_i × (E(r_m) - r_f)
β_i = Cov(r_i, r_m) / Var(r_m)

Modèle à facteurs (Fama-French) : ajout taille (SMB) et value (HML).
"""

ACCOUNTING_DEEP_COURSE = """# Comptabilité Approfondie — cours synthétique

## 1. Normes IFRS vs Comptabilité française

Principes IFRS : primauté de l'image fidèle, fair value, substance over form.
Différences clés : activation des frais de développement, réévaluation actifs,
comptabilisation des contrats de location (IFRS 16).

Plan comptable français (PCG) : nomenclature par classes, principe de prudence
plus marqué, moins de fair value.

## 2. Consolidation

Périmètre : contrôle exclusif (intégration globale), contrôle conjoint
(mise en équivalence), influence notable (mise en équivalence).

Écart d'acquisition (goodwill) : différence entre coût d'acquisition et quote-part
de l'actif net réévalué. Test de dépréciation annuel (IAS 36).

Traitement des opérations internes : élimination des produits/charges,
plus-values latentes, dividendes intragroupe.

## 3. Instruments financiers (IFRS 9)

Classification : amortized cost, FVOCI, FVTPL selon business model et
caractéristiques contractuelles (SPPI test).

Dépréciation : modèle ECL (Expected Credit Losses) en 3 stades.
Stade 1 : ECL à 12 mois. Stade 2 : ECL à vie. Stade 3 : crédit altéré.

Couverture comptable (hedge accounting) : fair value hedge, cash flow hedge,
net investment hedge. Documentation et efficacité requises.

## 4. Reconnaissance des produits (IFRS 15)

Modèle en 5 étapes : identifier contrat, obligations de performance,
prix de transaction, allocation, reconnaissance à la satisfaction.

Licence de brevet : reconnaissance à un moment (droit d'usage) ou
sur période (droit d'accès).

## 5. Locations (IFRS 16)

Locataire : droit d'utilisation (asset) + dette de location (liability)
pour quasi tous les baux. Exception : courts termes et faible valeur.

Bailleur : classification inchangée (location-financement / location-simple).

Impact ratios : EBITDA ↑, Dette ↑, ROCE ↓ (dénominateur ↑).
"""

COURSES = {
    "finance": ("Évaluation d'entreprise — cours synthétique", FINANCE_COURSE),
    "comptabilite": ("Comptabilité générale — cours synthétique", ACCOUNTING_COURSE),
    "maths": ("Mathématiques financières — cours synthétique", MATH_COURSE),
    "dcf": ("DCF Valuation — cours synthétique", DCF_COURSE),
    "market_finance": ("Finance de Marché — cours synthétique", MARKET_FINANCE_COURSE),
    "accounting_deep": ("Comptabilité Approfondie — cours synthétique", ACCOUNTING_DEEP_COURSE),
}

# --------------------------------------------------------------------------- #
# Course used by ``python -m study_coach.demo``
# --------------------------------------------------------------------------- #

DEMO_TITLE = "Évaluation d'entreprise — cours de démonstration"
DEMO_COURSE = """# Évaluation d'entreprise — cours de démonstration

## 1. La valeur actuelle nette

La valeur actuelle nette est la somme des flux de trésorerie futurs actualisés
moins l'investissement initial. Un projet dont la VAN est positive augmente la
valeur de l'entreprise.

Exemple : pour un investissement initial de 100 000 € et des flux actualisés de
40 000 €, la VAN vaut -60 000 €.

## 2. Le coût moyen pondéré du capital

Le coût moyen pondéré du capital est le coût moyen du financement de
l'entreprise. Il combine le coût de la dette et le coût des fonds propres.

Dans notre exemple, le coût de la dette vaut 6 % et le taux d'IS vaut 25 %.

## 3. Le flux de trésorerie disponible

Le flux de trésorerie disponible est le flux de trésorerie généré par
l'activité, indépendamment du financement de l'entreprise.

## 4. Le ratio de rentabilité

Le ratio de rentabilité désigne le rapport entre le résultat net et le chiffre
d'affaires.
"""
