"""Structured, local numerical practice aligned with the VC 2025 past exam."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .ingest import CorpusIndex


@dataclass(frozen=True)
class PracticeStep:
    step_id: str
    group: str
    label: str
    unit: str
    expected: float | None
    tolerance: float
    points: float
    explanation: str
    input_type: str = "number"
    choices: tuple[str, ...] = ()
    expected_choice: str | None = None


@dataclass(frozen=True)
class PracticeCase:
    case_id: str
    exam_question: str
    title: str
    chapter: str
    prompt: str
    citation_query: str
    citation_source_contains: str
    course_query: str
    steps: tuple[PracticeStep, ...]
    official_question_score: float | None = None
    rubric_note: str | None = None
    course_section: str | None = None

    @property
    def max_score(self) -> float:
        return round(sum(step.points for step in self.steps), 2)

    def public(self, citations: list[dict[str, Any]], *, stats: dict[str, Any]) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "exam_question": self.exam_question,
            "title": self.title,
            "chapter": self.chapter,
            "prompt": self.prompt,
            "max_score": self.max_score,
            "official_question_score": self.official_question_score or self.max_score,
            "rubric": self.rubric_note or "Barème pédagogique NAGe, indicatif; le corrigé officiel ne publie pas de grille de points partiels.",
            "steps": [
                {
                    "step_id": step.step_id, "group": step.group, "label": step.label, "unit": step.unit,
                    "points": step.points, "input_type": step.input_type, "choices": list(step.choices),
                }
                for step in self.steps
            ],
            "citations": citations,
            "stats": stats,
        }


_EXAM_SOURCE = "vc final exam 2025 solutions"

_CASES: tuple[PracticeCase, ...] = (
    PracticeCase(
        "VC25-Q16", "Q16", "VC Method : ownership requise", "TOPIC 3",
        "Un VC investit 5 M$ aujourd’hui. La sortie est estimée à 50 M$ dans 5 ans et son hurdle rate est de 40 %. Calcule le CCM requis, la valeur de sortie nécessaire pour le VC, puis sa part du capital.",
        "Palooka Products 5 million 50 million 5 years 40% hurdle 5.378 9.297 54%",
        _EXAM_SOURCE,
        "venture capital method hurdle rate cash-on-cash multiple post-money ownership formula",
        (
            PracticeStep("ccm", "1 · Rendement requis", "CCM requis", "x", 5.378, 0.02, 1.0, "CCM = (1 + hurdle rate)^n = 1,4^5 = 5,378x."),
            PracticeStep("proceeds", "2 · Part du produit de sortie", "Produit requis à la sortie", "M$", 26.89, 0.08, 1.0, "Produit revenant au VC = investissement × CCM = 5 × 5,378 = 26,89 M$."),
            PracticeStep("ownership", "3 · Ownership", "Part du capital acceptée par le VC", "%", 53.8, 0.8, 1.0, "Ownership = produit requis / valeur totale de sortie = 26,89 / 50 = 53,8 %, arrondi à 54 %."),
        ),
    ),
    PracticeCase(
        "VC25-Q17", "Q17", "Cap table fully diluted", "TOPIC 3",
        "La société a 5 millions d’actions fondateurs. Le VC investit 2 M$ sur une valorisation post-money de 8 M$. Le pool d’options doit représenter 20 % post-money. Retrouve les fractions de propriété et le nombre d’actions fully diluted.",
        "startup 5m founder shares VC invests 2m 8m post-money valuation 20% post-money options pool founders 55% 9090909",
        _EXAM_SOURCE,
        "fully diluted founder shares post-money options pool venture capital cap table",
        (
            PracticeStep("vc_ownership", "1 · Ownership", "Part du VC", "%", 25.0, 0.3, 0.6, "Part du VC = 2 / 8 = 25 %."),
            PracticeStep("founder_ownership", "1 · Ownership", "Part des fondateurs", "%", 55.0, 0.3, 0.6, "Part des fondateurs = 100 % − 25 % VC − 20 % pool = 55 %."),
            PracticeStep("total_shares", "2 · Nombre d’actions", "Total fully diluted", "millions d’actions", 9.090909, 0.02, 0.6, "Les 5 millions d’actions fondateurs représentent 55 % : total = 5 / 0,55 = 9,091 millions."),
            PracticeStep("pool_shares", "2 · Nombre d’actions", "Actions du pool", "millions d’actions", 1.818182, 0.02, 0.6, "Pool = 20 % × 9,091 = 1,818 million d’actions."),
            PracticeStep("vc_shares", "2 · Nombre d’actions", "Actions du VC", "millions d’actions", 2.272727, 0.02, 0.6, "Actions VC = 25 % × 9,091 = 2,273 millions."),
        ),
    ),
    PracticeCase(
        "VC25-Q18", "Q18", "Conversion, dilution et IRR", "TOPIC 3",
        "Miller investit 5 M$ contre 1 million d’actions préférentielles convertibles en 2 actions ordinaires chacune. Après conversion, 15 millions d’actions existent; l’IPO en émet 3 millions. Le cours de l’action à la sortie est de 25 $ après 8 ans. Calcule l’ownership puis l’IRR.",
        "Miller Venture Capital 5 million investment 8 years 1 million convertible preferred 2 common shares 15 million shares IPO 3 million 11% stock 25",
        _EXAM_SOURCE,
        "convertible preferred shares 2 common shares IPO 3 million shares 11% cash on cash IRR 8 years",
        (
            PracticeStep("converted_shares", "1 · Conversion", "Actions ordinaires après conversion", "millions d’actions", 2.0, 0.02, 0.75, "1 million d’actions préférentielles × 2 = 2 millions d’actions ordinaires."),
            PracticeStep("ipo_total", "2 · Dilution à l’IPO", "Actions après émission à l’IPO", "millions d’actions", 18.0, 0.02, 0.5, "Total après IPO = 15 + 3 = 18 millions d’actions."),
            PracticeStep("ownership", "2 · Dilution à l’IPO", "Ownership de Miller après IPO", "%", 11.1, 0.3, 0.75, "Ownership = 2 / 18 = 11,1 %."),
            PracticeStep("exit_value", "3 · Rendement", "Valeur de la participation à la sortie", "M$", 50.0, 0.5, 0.75, "Produit de sortie = 2 millions d’actions × 25 $ = 50 M$."),
            PracticeStep("ccm", "3 · Rendement", "CCM de l’investissement", "x", 10.0, 0.1, 0.5, "CCM = valeur de sortie / investissement initial = 50 / 5 = 10x."),
            PracticeStep("irr", "3 · Rendement", "IRR annuel composé", "%", 33.35, 0.8, 0.75, "IRR = CCM^(1/8) − 1 = 10^(1/8) − 1 ≈ 33,4 %, arrondi à 33 %."),
        ),
    ),
    PracticeCase(
        "VC25-Q19", "Q19", "Financements successifs et dilution à la sortie", "TOPIC 3",
        "La startup prévoit une sortie à 6 Md$ dans 7 ans. Les tours sont : Seed (1 M$ investi, multiple cible 8x), Series A (25 M$, 5x), Series B (50 M$, 4x), Series C (200 M$, 3x). Remonte les post-money à partir de la sortie, puis calcule l’ownership après chaque tour et à la sortie.",
        "startup strategic acquisition 6 billion seed 1 million target multiple 8 series A 25 5 series B 50 4 series C 200 3 fully diluted ownership founders 47",
        _EXAM_SOURCE,
        "venture capital multiple method successive rounds post-money valuation pre-money ownership dilution founder exit 47%",
        (
            PracticeStep("series_c_post", "1 · Valorisations à rebours", "Post-money Series C", "M$", 2000.0, 2.0, 0.5, "Post-money C = sortie / multiple C = 6 000 / 3 = 2 000 M$."),
            PracticeStep("series_b_post", "1 · Valorisations à rebours", "Post-money Series B", "M$", 450.0, 1.0, 0.5, "Pre-money C = 2 000 − 200 = 1 800 M$; post-money B = 1 800 / 4 = 450 M$."),
            PracticeStep("series_a_post", "1 · Valorisations à rebours", "Post-money Series A", "M$", 80.0, 0.5, 0.25, "Pre-money B = 450 − 50 = 400 M$; post-money A = 400 / 5 = 80 M$."),
            PracticeStep("seed_post", "1 · Valorisations à rebours", "Post-money Seed", "M$", 6.875, 0.05, 0.25, "Pre-money A = 80 − 25 = 55 M$; post-money Seed = 55 / 8 = 6,875 M$."),
            PracticeStep("seed_round_pct", "2 · Ownership après chaque tour", "Part Seed après le tour", "%", 14.55, 0.35, 0.25, "Ownership Seed = 1 / 6,875 = 14,55 %."),
            PracticeStep("series_a_round_pct", "2 · Ownership après chaque tour", "Part Series A après le tour", "%", 31.25, 0.35, 0.25, "Ownership A = 25 / 80 = 31,25 %."),
            PracticeStep("series_b_round_pct", "2 · Ownership après chaque tour", "Part Series B après le tour", "%", 11.11, 0.35, 0.25, "Ownership B = 50 / 450 = 11,11 %."),
            PracticeStep("series_c_round_pct", "2 · Ownership après chaque tour", "Part Series C après le tour", "%", 10.0, 0.35, 0.25, "Ownership C = 200 / 2 000 = 10 %."),
            PracticeStep("founder_exit_pct", "3 · Ownership à la sortie", "Part des fondateurs à la sortie", "%", 47.0, 0.7, 0.5, "Les fondateurs conservent successivement (1 − Seed) × (1 − A) × (1 − B) × (1 − C) ≈ 47 %."),
            PracticeStep("seed_exit_pct", "3 · Ownership à la sortie", "Part Seed à la sortie", "%", 8.0, 0.5, 0.5, "Part Seed à la sortie = 14,55 % × rétention A × rétention B × rétention C ≈ 8 %."),
            PracticeStep("series_a_exit_pct", "3 · Ownership à la sortie", "Part Series A à la sortie", "%", 25.0, 0.7, 0.5, "Part A à la sortie = 31,25 % × rétention B × rétention C = 25 %."),
            PracticeStep("series_b_exit_pct", "3 · Ownership à la sortie", "Part Series B à la sortie", "%", 10.0, 0.5, 0.5, "Part B à la sortie = 11,11 % × rétention C = 10 %."),
            PracticeStep("series_c_exit_pct", "3 · Ownership à la sortie", "Part Series C à la sortie", "%", 10.0, 0.5, 0.5, "La participation Series C est de 200 / 2 000 = 10 %; aucun tour ultérieur ne la dilue."),
        ),
    ),
    PracticeCase(
        "VC25-Q20A", "Q20 a", "Comparer les term sheets", "TOPIC 4",
        "Du point de vue des fondateurs de Butchered Data, choisis l’offre la plus favorable dans chacune des cinq catégories. Compare les données des offres Alpha et Mega; il faut aussi tenir compte de la cap table et du contrôle.",
        "Butchered Data Alpha Mega term sheet valuation ownership anti-dilution option pool vesting board",
        _EXAM_SOURCE,
        "liquidation preference anti-dilution broad based weighted average full ratchet vesting board control option pool",
        (
            PracticeStep("valuation", "a · Term sheet", "Valorisation et part des fondateurs", "offre", None, 0, 0.8, "Mega : les fondateurs détiennent 31,9 % contre 26,4 % avec Alpha, selon la cap table fournie." , "choice", ("Alpha", "Mega"), "Mega"),
            PracticeStep("anti_dilution", "a · Term sheet", "Protection anti-dilution", "offre", None, 0, 0.8, "Alpha : le weighted average broad-based est moins sévère pour les fondateurs qu’un full ratchet, qui réajuste le prix de conversion au prix du nouveau tour." , "choice", ("Alpha", "Mega"), "Alpha"),
            PracticeStep("option_pool", "a · Term sheet", "Taille du pool d’options", "offre", None, 0, 0.8, "Mega : le pool post-money est de 15 % contre 25 % pour Alpha, donc une dilution moindre des autres actionnaires." , "choice", ("Alpha", "Mega"), "Mega"),
            PracticeStep("vesting", "a · Term sheet", "Conditions de vesting du CEO", "offre", None, 0, 0.8, "Alpha : l’offre décrite n’ajoute pas de clause de reverse vesting du CEO; Mega rend 75 % des actions sujettes au rachat sur 36 mois." , "choice", ("Alpha", "Mega"), "Alpha"),
            PracticeStep("board", "a · Term sheet", "Contrôle du board", "offre", None, 0, 0.8, "Alpha : les actions ordinaires désignent deux sièges sur trois; avec Mega, les investisseurs en désignent deux." , "choice", ("Alpha", "Mega"), "Alpha"),
        ),
        15,
        "Barème pédagogique indicatif NAGe : 4 points attribués à cette partie de Q20, sur 15 au total. Le corrigé officiel ne répartit pas les points par sous-partie.",
    ),
    PracticeCase(
        "VC25-Q20B", "Q20 b", "Payoffs selon la valeur de sortie", "TOPIC 4",
        "Calcule le montant reçu par Alpha et Mega pour chaque valeur de sortie. Alpha détient 4 M$ de preferred convertible et 44,4 % sur une base convertie. Mega a investi 6 M$ en preferred participante, participe à 50 % après sa préférence de 1x et son retour est plafonné à 2,5x; la conversion complète devient préférable au-delà du seuil indiqué par le corrigé.",
        "Butchered Data exit value Alpha payoff Mega payoff 5 10 28 35 4.44 12.43 15.54 17.5",
        _EXAM_SOURCE,
        "participating preferred liquidation preference cap as-converted payoff convertible preferred exit valuation",
        (
            PracticeStep("alpha_5", "b · Payoff à la sortie", "Alpha à 5 M$ de sortie", "M$", 4.0, 0.02, 1, "Alpha reçoit le plus élevé entre la préférence de 4 M$ et la conversion : max(4; 44,4 % × 5) = 4 M$."),
            PracticeStep("mega_5", "b · Payoff à la sortie", "Mega à 5 M$ de sortie", "M$", 5.0, 0.02, 1, "Le produit disponible est inférieur à la préférence de 6 M$; Mega reçoit le produit disponible, soit 5 M$."),
            PracticeStep("alpha_10", "b · Payoff à la sortie", "Alpha à 10 M$ de sortie", "M$", 4.44, 0.04, 1, "Conversion : 44,4 % × 10 = 4,44 M$, supérieure à la préférence de 4 M$."),
            PracticeStep("mega_10", "b · Payoff à la sortie", "Mega à 10 M$ de sortie", "M$", 8.0, 0.03, 1, "Préférence participante : 6 + 50 % × (10 − 6) = 8 M$, sous le cap de 15 M$."),
            PracticeStep("alpha_28", "b · Payoff à la sortie", "Alpha à 28 M$ de sortie", "M$", 12.43, 0.05, 1, "Conversion : 44,4 % × 28 ≈ 12,43 M$, supérieure à la préférence de 4 M$."),
            PracticeStep("mega_28", "b · Payoff à la sortie", "Mega à 28 M$ de sortie", "M$", 15.0, 0.03, 1, "La préférence participante atteint 17 M$ avant application du cap; le paiement est plafonné à 2,5 × 6 = 15 M$."),
            PracticeStep("alpha_35", "b · Payoff à la sortie", "Alpha à 35 M$ de sortie", "M$", 15.54, 0.06, 1, "Conversion : 44,4 % × 35 ≈ 15,54 M$, supérieure à la préférence de 4 M$."),
            PracticeStep("mega_35", "b · Payoff à la sortie", "Mega à 35 M$ de sortie", "M$", 17.5, 0.04, 1, "La conversion complète donne 50 % × 35 = 17,5 M$, supérieure au cap de 15 M$; le seuil de conversion est 30 M$."),
        ),
        15,
        "Barème pédagogique indicatif NAGe : 8 points attribués à cette partie de Q20, sur 15 au total. Le corrigé officiel ne répartit pas les points par sous-partie.",
    ),
    PracticeCase(
        "VC25-Q20C", "Q20 c", "Full ratchet en Series B", "TOPIC 4",
        "Si Butchered Data choisit Mega, la Series B émet de nouvelles actions à 0,90 $ par action. Le prix de conversion de Mega est ajusté par full ratchet depuis son prix initial de 1 $. Calcule les actions ordinaires reçues par les 6 millions d’actions preferred de Mega.",
        "Butchered Data Mega Series B issue price 0.90 full ratchet common shares 6.67 million",
        _EXAM_SOURCE,
        "full ratchet anti-dilution conversion price preferred shares new issue price",
        (
            PracticeStep("common_shares", "c · Conversion", "Actions ordinaires après full ratchet", "M d’actions", 6.67, 0.02, 3, "Le full ratchet ramène le prix de conversion de 1,00 $ à 0,90 $. Actions converties = 6 M$ / 0,90 $ = 6,67 millions."),
        ),
        15,
        "Barème pédagogique indicatif NAGe : 3 points attribués à cette partie de Q20, sur 15 au total. Le corrigé officiel ne répartit pas les points par sous-partie.",
    ),
    PracticeCase(
        "VC25-Q21A", "Q21 a", "Calcul des offres initiales", "TOPIC 3",
        "Ali Baba détient 3 millions d’actions. VW propose 2 M$ à 5 M$ post-money; XY propose 1 M$ à 3 M$ pre-money. Pour chaque offre, calcule les valeurs pre-money et post-money, le prix par action, les actions nouvelles, le total d’actions et la part du fondateur. Montants en millions.",
        "Magical Genie Veronika Windel Xavier Ypsalia initial financing pre-money post-money price per share founder ownership 5 4 60 75",
        _EXAM_SOURCE,
        "pre-money post-money valuation price per share new shares founder ownership financing round",
        (
            PracticeStep("vw_pre", "a · Offre VW", "Pre-money VW", "M$", 3, 0.02, 0.25, "Pre-money = post-money − investissement = 5 − 2 = 3 M$."),
            PracticeStep("vw_post", "a · Offre VW", "Post-money VW", "M$", 5, 0.02, 0.25, "La valorisation post-money est donnée : 5 M$."),
            PracticeStep("vw_price", "a · Offre VW", "Prix par action VW", "$ / action", 1, 0.02, 0.25, "Prix = pre-money / actions existantes = 3 M$ / 3 M actions = 1 $ par action."),
            PracticeStep("vw_new_shares", "a · Offre VW", "Actions nouvelles VW", "M d’actions", 2, 0.02, 0.25, "Actions nouvelles = investissement / prix = 2 M$ / 1 $ = 2 millions."),
            PracticeStep("vw_total_shares", "a · Offre VW", "Total d’actions VW", "M d’actions", 5, 0.02, 0.25, "Total = 3 millions d’actions du fondateur + 2 millions nouvelles = 5 millions."),
            PracticeStep("vw_founder_pct", "a · Offre VW", "Part du fondateur VW", "%", 60, 0.3, 0.25, "Part = 3 / 5 = 60 %."),
            PracticeStep("xy_pre", "a · Offre XY", "Pre-money XY", "M$", 3, 0.02, 0.25, "La pre-money de XY est donnée : 3 M$."),
            PracticeStep("xy_post", "a · Offre XY", "Post-money XY", "M$", 4, 0.02, 0.25, "Post-money = pre-money + investissement = 3 + 1 = 4 M$."),
            PracticeStep("xy_price", "a · Offre XY", "Prix par action XY", "$ / action", 1, 0.02, 0.25, "Prix = pre-money / actions existantes = 3 M$ / 3 M actions = 1 $ par action."),
            PracticeStep("xy_new_shares", "a · Offre XY", "Actions nouvelles XY", "M d’actions", 1, 0.02, 0.25, "Actions nouvelles = investissement / prix = 1 M$ / 1 $ = 1 million."),
            PracticeStep("xy_total_shares", "a · Offre XY", "Total d’actions XY", "M d’actions", 4, 0.02, 0.25, "Total = 3 millions d’actions du fondateur + 1 million nouvelle = 4 millions."),
            PracticeStep("xy_founder_pct", "a · Offre XY", "Part du fondateur XY", "%", 75, 0.3, 0.25, "Part = 3 / 4 = 75 %."),
        ),
        15,
        "Barème pédagogique indicatif NAGe : 3 points attribués à cette partie de Q21, sur 15 au total. Le corrigé officiel ne répartit pas les points par sous-partie.",
    ),
    PracticeCase(
        "VC25-Q21B", "Q21 b", "Second tour selon le scénario", "TOPIC 3",
        "Calcule les six lignes de la table de financement du second tour pour les trois scénarios avec financement : pre-money, post-money, prix par action, actions nouvelles, total d’actions et ownership du fondateur. VW au scénario 1 n’a pas de second tour : sa cap table reste celle de la partie a. Montants et actions en millions.",
        "Magical Genie scenario 1 scenario 2 VW XY second financing round pre-money post-money new shares founder ownership 0.5 4 8 66.7 33.3 25",
        _EXAM_SOURCE,
        "financing rounds pre-money post-money share price dilution founder ownership new shares",
        (
            PracticeStep("s1_xy_pre", "b · Scénario 1 · XY", "Pre-money XY", "M$", 8, 0.05, 0.5, "La société a 4 M d’actions existantes à 2 $ : pre-money = 4 × 2 = 8 M$."),
            PracticeStep("s1_xy_post", "b · Scénario 1 · XY", "Post-money XY", "M$", 9, 0.05, 0.5, "Post-money = pre-money + investissement = 8 + 1 = 9 M$."),
            PracticeStep("s1_xy_price", "b · Scénario 1 · XY", "Prix par action", "$ / action", 2, 0.02, 0.5, "Le prix de souscription du scénario 1 est donné : 2 $ par action."),
            PracticeStep("s1_xy_new", "b · Scénario 1 · XY", "Actions nouvelles", "M d’actions", 0.5, 0.02, 0.5, "Actions nouvelles = 1 M$ / 2 $ = 0,5 million."),
            PracticeStep("s1_xy_total", "b · Scénario 1 · XY", "Total d’actions", "M d’actions", 4.5, 0.02, 0.5, "Total = 4 + 0,5 = 4,5 millions d’actions."),
            PracticeStep("s1_xy_founder_pct", "b · Scénario 1 · XY", "Ownership du fondateur", "%", 66.7, 0.4, 0.5, "Ownership = 3 / 4,5 = 66,7 %."),
            PracticeStep("s2_vw_pre", "b · Scénario 2 · VW", "Pre-money VW", "M$", 1.25, 0.03, 0.5, "Les 5 M d’actions existantes valent 0,25 $ chacune : pre-money = 1,25 M$."),
            PracticeStep("s2_vw_post", "b · Scénario 2 · VW", "Post-money VW", "M$", 2.25, 0.03, 0.5, "Post-money = 1,25 + 1 = 2,25 M$."),
            PracticeStep("s2_vw_price", "b · Scénario 2 · VW", "Prix par action", "$ / action", 0.25, 0.01, 0.5, "Le prix de souscription du scénario 2 est donné : 0,25 $ par action."),
            PracticeStep("s2_vw_new", "b · Scénario 2 · VW", "Actions nouvelles", "M d’actions", 4, 0.05, 0.5, "Actions nouvelles = 1 M$ / 0,25 $ = 4 millions."),
            PracticeStep("s2_vw_total", "b · Scénario 2 · VW", "Total d’actions", "M d’actions", 9, 0.05, 0.5, "Total = 5 + 4 = 9 millions d’actions."),
            PracticeStep("s2_vw_founder_pct", "b · Scénario 2 · VW", "Ownership du fondateur", "%", 33.3, 0.4, 0.5, "Ownership = 3 / 9 = 33,3 %."),
            PracticeStep("s2_xy_pre", "b · Scénario 2 · XY", "Pre-money XY", "M$", 1, 0.03, 0.5, "Les 4 M d’actions existantes valent 0,25 $ chacune : pre-money = 1 M$."),
            PracticeStep("s2_xy_post", "b · Scénario 2 · XY", "Post-money XY", "M$", 3, 0.03, 0.5, "Post-money = 1 + 2 = 3 M$."),
            PracticeStep("s2_xy_price", "b · Scénario 2 · XY", "Prix par action", "$ / action", 0.25, 0.01, 0.5, "Le prix de souscription du scénario 2 est donné : 0,25 $ par action."),
            PracticeStep("s2_xy_new", "b · Scénario 2 · XY", "Actions nouvelles", "M d’actions", 8, 0.05, 0.5, "Actions nouvelles = 2 M$ / 0,25 $ = 8 millions."),
            PracticeStep("s2_xy_total", "b · Scénario 2 · XY", "Total d’actions", "M d’actions", 12, 0.05, 0.5, "Total = 4 + 8 = 12 millions d’actions."),
            PracticeStep("s2_xy_founder_pct", "b · Scénario 2 · XY", "Ownership du fondateur", "%", 25, 0.3, 0.5, "Ownership = 3 / 12 = 25 %."),
        ),
        15,
        "Barème pédagogique indicatif NAGe : 9 points attribués à cette partie de Q21, sur 15 au total. Le corrigé officiel ne répartit pas les points par sous-partie.",
    ),
    PracticeCase(
        "VC25-Q21C", "Q21 c", "Valeur espérée des offres", "TOPIC 3",
        "Le scénario 1 a une probabilité de 75 % et le scénario 2 de 25 %. Pour VW et XY, calcule l’ownership espérée du fondateur puis sa richesse finale espérée si la sortie vaut 10 M$.",
        "Magical Genie expected ownership expected final wealth 53.33 56.25 5.333 5.625 probability scenario",
        _EXAM_SOURCE,
        "expected ownership probability weighted scenarios expected value exit wealth founder dilution",
        (
            PracticeStep("vw_expected_pct", "c · Offre VW", "Ownership espérée du fondateur", "%", 53.33, 0.15, 0.75, "Ownership espérée = 75 % × 60 % + 25 % × 33,3 % ≈ 53,33 %."),
            PracticeStep("vw_expected_wealth", "c · Offre VW", "Richesse finale espérée", "M$", 5.333, 0.03, 0.75, "Richesse espérée = 53,33 % × 10 M$ ≈ 5,333 M$."),
            PracticeStep("xy_expected_pct", "c · Offre XY", "Ownership espérée du fondateur", "%", 56.25, 0.15, 0.75, "Ownership espérée = 75 % × 66,7 % + 25 % × 25 % = 56,25 %."),
            PracticeStep("xy_expected_wealth", "c · Offre XY", "Richesse finale espérée", "M$", 5.625, 0.03, 0.75, "Richesse espérée = 56,25 % × 10 M$ = 5,625 M$."),
        ),
        15,
        "Barème pédagogique indicatif NAGe : 3 points attribués à cette partie de Q21, sur 15 au total. Le corrigé officiel ne répartit pas les points par sous-partie.",
        course_section="4. TrafalgarTech",
    ),
)


def _parse_number(raw: Any, *, unit: str) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        has_percent = False
    elif isinstance(raw, str) and len(raw) <= 64:
        value_text = raw.strip().replace("−", "-").replace(" ", " ")
        has_percent = "%" in value_text
        value_text = re.sub(r"(?i)(millions?|m\$|usd|eur|[$€%x\s])", "", value_text)
        if not re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)", value_text):
            return None
        try:
            value = float(value_text.replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(value):
        return None
    if unit == "%" and not has_percent and abs(value) <= 1:
        value *= 100
    return round(value, 6)


def _display_expected(step: PracticeStep) -> str:
    if step.input_type == "choice":
        return step.expected_choice or ""
    if step.unit == "%":
        value = f"{step.expected:.2f}".rstrip("0").rstrip(".")
        return f"{value} %"
    value = f"{float(step.expected or 0):.6g}"
    return f"{value} {step.unit}".strip()


def _parse_choice(raw: Any, step: PracticeStep) -> str | None:
    if not isinstance(raw, str) or len(raw) > 80:
        return None
    candidate = raw.strip().casefold()
    for option in step.choices:
        if candidate in {option.casefold(), option[0].casefold()}:
            return option
    return None


class CasePracticeEngine:
    """Persist attempts locally and grade against explicit educational rubrics."""

    def __init__(self, index: CorpusIndex, db_path: str | Path):
        self.index = index
        self._lock = RLock()
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS case_practice_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, submitted_at TEXT NOT NULL,
                score REAL NOT NULL, max_score REAL NOT NULL, answers_json TEXT NOT NULL, result_json TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _case(case_id: str) -> PracticeCase:
        for item in _CASES:
            if item.case_id == case_id:
                return item
        raise KeyError("Exercice introuvable.")

    def _citations(self, case: PracticeCase, *, reveal_excerpt: bool = False) -> list[dict[str, Any]]:
        hits = self.index.search(case.citation_query, limit=20)
        official = [hit for hit in hits if case.citation_source_contains in Path(hit.source_path).name.casefold()]
        course = self.index.search(case.course_query, limit=20, section=case.course_section or case.chapter)
        result: list[dict[str, Any]] = []
        for hit in (official[:1] + course[:1]):
            cite = hit.citation()
            if not reveal_excerpt:
                cite.pop("excerpt", None)
            if not any(existing["source"] == cite["source"] and existing["page"] == cite["page"] for existing in result):
                result.append(cite)
        return result

    def _stats(self, case_id: str) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT score, max_score, result_json FROM case_practice_attempts WHERE case_id=? ORDER BY id DESC",
            (case_id,),
        ).fetchall()
        scores = [float(row["score"]) for row in rows]
        max_score = float(rows[0]["max_score"]) if rows else self._case(case_id).max_score
        latest_result = json.loads(rows[0]["result_json"]) if rows else None
        return {
            "attempts": len(rows),
            "best_score": max(scores) if scores else None,
            "max_score": max_score,
            "latest_result": latest_result,
            "local_only": True,
        }

    def list_cases(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cases": [case.public(self._citations(case), stats=self._stats(case.case_id)) for case in _CASES],
                "local_only": True,
            }

    def submit(self, case_id: str, answers: dict[str, Any]) -> dict[str, Any]:
        case = self._case(case_id)
        if not isinstance(answers, dict):
            raise ValueError("Les réponses doivent être fournies sous forme de champs connus.")
        known_steps = {step.step_id: step for step in case.steps}
        if set(answers) - set(known_steps):
            raise ValueError("Une réponse ne correspond à aucun champ de cet exercice.")
        with self._lock:
            graded: list[dict[str, Any]] = []
            score = 0.0
            safe_answers: dict[str, float | str | None] = {}
            for step in case.steps:
                if step.input_type == "choice":
                    entered_choice = _parse_choice(answers.get(step.step_id), step)
                    safe_answers[step.step_id] = entered_choice
                    entered: float | str | None = entered_choice
                    valid_answer = entered_choice is not None
                    correct = valid_answer and entered_choice == step.expected_choice
                    entered_display = entered_choice or ""
                    expected: float | str | None = step.expected_choice
                else:
                    entered_number = _parse_number(answers.get(step.step_id), unit=step.unit)
                    safe_answers[step.step_id] = entered_number
                    entered = entered_number
                    valid_answer = entered_number is not None
                    correct = valid_answer and step.expected is not None and abs(entered_number - step.expected) <= step.tolerance
                    entered_display = f"{entered_number:g}" if entered_number is not None else ""
                    expected = step.expected
                awarded = step.points if correct else 0.0
                score += awarded
                graded.append({
                    "step_id": step.step_id,
                    "group": step.group,
                    "label": step.label,
                    "unit": step.unit,
                    "input_type": step.input_type,
                    "entered": entered,
                    "entered_display": entered_display,
                    "valid_number": step.input_type == "number" and valid_answer,
                    "valid_answer": valid_answer,
                    "correct": correct,
                    "awarded": awarded,
                    "points": step.points,
                    "expected": expected,
                    "expected_display": _display_expected(step),
                    "explanation": step.explanation,
                })
            max_score = case.max_score
            citations = self._citations(case, reveal_excerpt=True)
            result = {
                "case_id": case.case_id,
                "exam_question": case.exam_question,
                "score": round(score, 2),
                "max_score": max_score,
                "percent": round(score / max_score * 100) if max_score else 0,
                "rubric": case.rubric_note or "Barème pédagogique NAGe, indicatif; le corrigé officiel ne publie pas de grille de points partiels.",
                "steps": graded,
                "citations": citations,
                "local_only": True,
            }
            self._conn.execute(
                "INSERT INTO case_practice_attempts(case_id,submitted_at,score,max_score,answers_json,result_json) VALUES(?,?,?,?,?,?)",
                (case_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), score, max_score,
                 json.dumps(safe_answers, ensure_ascii=False), json.dumps(result, ensure_ascii=False)),
            )
            self._conn.commit()
            result["stats"] = self._stats(case_id)
            return result


__all__ = ["CasePracticeEngine"]
