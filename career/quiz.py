"""Progressive, corpus-derived quiz questions and chapter mastery."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from functools import wraps
from threading import RLock
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .ingest import CorpusIndex


def _sqlite_locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class QuizQuestion:
    question_id: str
    chapter: str
    prompt: str
    options: list[str]
    correct_index: int
    difficulty: str
    citation: dict[str, Any]
    explanation: str = ""

    def public(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("correct_index")
        payload.pop("explanation")
        return payload


@dataclass(frozen=True)
class _QuestionSeed:
    prompt: str
    options: tuple[str, ...]
    correct_index: int
    citation_query: str
    explanation: str
    citation_source_contains: str = ""


_QUESTION_BANK: dict[str, tuple[_QuestionSeed, ...]] = {
    "TOPIC 1": (
        _QuestionSeed(
            "Pourquoi un VC finance-t-il souvent une startup par étapes ?",
            (
                "Pour conditionner les tranches aux jalons, réduire l’incertitude et garder l’option d’arrêter ou de poursuivre.",
                "Pour garantir aux fondateurs une valorisation identique à chaque tour.",
                "Pour supprimer tout risque d’agence et toute dilution future.",
                "Pour remplacer l’analyse du marché par une garantie de rendement.",
            ), 0, "staged financing milestones reduce uncertainty option abandon",
            "Le cours relie le financement par étapes aux jalons, à la réduction des asymétries d’information et à l’option de ne pas financer la suite si les résultats sont faibles.",
            "Topic_1_",
        ),
        _QuestionSeed(
            "À quoi sert principalement le tour seed par rapport à une Series A ?",
            (
                "Construire et valider le produit avant de financer sa mise à l’échelle.",
                "Financer une sortie secondaire des investisseurs historiques.",
                "Remplacer les investisseurs en capital par de la dette senior.",
                "Distribuer des dividendes avant l’atteinte du product-market fit.",
            ), 0, "seed stage build validate product Series A scale",
            "Le cours distingue le seed, centré sur la construction et la validation du produit, de la Series A qui finance la croissance et la mise à l’échelle.",
            "Topic_1_",
        ),
    ),
    "TOPIC 2": (
        _QuestionSeed(
            "Quels sont les quatre axes de lignes de la Venture Evaluation Matrix du cours ?",
            (
                "Value proposition, industry, strategy, competitive advantage.",
                "Revenue, EBITDA, leverage, exit multiple.",
                "Seed, Series A, Series B, IPO.",
                "Product, valuation, liquidation preference, board rights.",
            ), 0, "Venture Evaluation Matrix Value Proposition Industry Strategy Competitive Advantage",
            "La matrice organise l’analyse en value proposition, industry, strategy et competitive advantage, puis la décline selon le client, l’entreprise, l’entrepreneur et l’attractivité.",
            "Topic_2_",
        ),
        _QuestionSeed(
            "Dans l’analyse du marché, que représente le SOM ?",
            (
                "La part de marché que l’entreprise peut raisonnablement capter dans son marché adressable.",
                "La totalité des dépenses mondiales dans une catégorie.",
                "Le revenu déjà reconnu en comptabilité.",
                "La valeur de sortie après application du hurdle rate.",
            ), 0, "TAM total addressable SAM serviceable available SOM obtainable market",
            "Le cours distingue TAM, SAM et SOM pour passer du marché total au marché servi puis à la part obtenable par la startup.",
            "Topic_2_",
        ),
    ),
    "TOPIC 3": (
        _QuestionSeed(
            "Une startup reçoit 1,2 M€ contre 20 % du capital après investissement. Quelle est sa valorisation post-money ?",
            ("6,0 M€", "4,8 M€", "5,0 M€", "7,2 M€"), 0,
            "post-money valuation investment ownership fraction formula",
            "Post-money = investissement / fraction détenue = 1,2 / 20 % = 6,0 M€. Pre-money = 6,0 − 1,2 = 4,8 M€.",
        ),
        _QuestionSeed(
            "Un VC investit 5 M€, vise une sortie de 50 M€ dans 5 ans et exige 40 % d’IRR. Quelle ownership initiale approche le VC method ?",
            ("54 %", "38 %", "26 %", "14 %"), 0,
            "VC ownership 54% CCM 1.4^5 5.378 post-money valuation 9.297",
            "MOIC requis = (1 + 40 %)⁵ = 5,378. Le produit requis à la sortie vaut 5 × 5,378 = 26,89 M€. Ownership = 26,89 / 50 = 53,8 %, soit environ 54 %.",
            "VC_final_exam_2025_solutions",
        ),
        _QuestionSeed(
            "Un investissement réalise un CCM de 13,8x en 5 ans. Quel IRR annuel composé est approximativement obtenu ?",
            ("69 %", "38 %", "13,8 %", "276 %"), 0,
            "CCM 13.8 IRR 13.8^(1/5) 69%",
            "IRR = CCM^(1/n) − 1 = 13,8^(1/5) − 1, soit environ 69 % par an.",
        ),
        _QuestionSeed(
            "Une startup a 5 millions d’actions fondateurs. Le VC investit 2 M$ dans une valorisation post-money de 8 M$ et exige un pool d’options de 20 % post-money. Quelle répartition donne le corrigé du cours ?",
            ("Fondateurs 55 % · pool 20 % · VC 25 %", "Fondateurs 60 % · pool 20 % · VC 20 %", "Fondateurs 50 % · pool 25 % · VC 25 %", "Fondateurs 65 % · pool 20 % · VC 15 %"), 0,
            "startup 5m founder shares VC invests 2m 8m post-money valuation 20% post-money options pool founders 55%",
            "La part du VC est 2/8 = 25 %. Le pool représente 20 %. Le solde revient aux fondateurs : 100 % − 25 % − 20 % = 55 %. Le corrigé fournit aussi les nombres d’actions correspondants.",
            "VC_final_exam_2025_solutions",
        ),
        _QuestionSeed(
            "Un fonds investit 5 M$ pour des préférentielles convertibles à raison de 2 actions ordinaires chacune. Il détient 1 million de préférentielles; après conversion, 15 millions d’actions existent, puis l’IPO en émet 3 millions. Quelle part détient-il après l’IPO ?",
            ("11 %", "13,3 %", "10 %", "20 %"), 0,
            "Miller Venture Capital 5 million investment 8 years 1 million convertible preferred 2 common shares 15 million shares IPO 3 million 11%",
            "La conversion donne 2 millions d’actions ordinaires. Après l’IPO, le total est 15 + 3 = 18 millions; la participation est 2/18 = 11,1 %, soit 11 %.",
            "VC_final_exam_2025_solutions",
        ),
        _QuestionSeed(
            "Dans le même cas, les 2 millions d’actions valent 25 $ chacune après 8 ans. Quel IRR annualisé approche le résultat du corrigé ?",
            ("33 %", "25 %", "10 %", "50 %"), 0,
            "Miller 2m common shares stock $25 50m cash on cash 10x IRR 8 years 33%",
            "La valeur de sortie est 2m × 25 $ = 50 M$. Le CCM est 50/5 = 10x. L’IRR composé sur 8 ans est 10^(1/8) − 1, environ 33 %.",
            "VC_final_exam_2025_solutions",
        ),
        _QuestionSeed(
            "Dans le cas Magical Genie du corrigé, avec 75 % de probabilité pour le scénario 1, quelle offre maximise la richesse finale espérée du fondateur ?",
            ("XY : 5,625 M$", "VW : 5,333 M$", "VW : 6,000 M$", "XY : 4,000 M$"), 0,
            "Magical Genie founder expected ownership expected final wealth VW XY scenario probability 75% 5.625 5.333",
            "Le corrigé compare les deux offres sous les scénarios de financement et retient XY : ownership espérée 56,25 % et richesse finale espérée 5,625 M$, contre 5,333 M$ pour VW.",
            "PEVC_final_exam_2024_solutions",
        ),
    ),
    "TOPIC 4": (
        _QuestionSeed(
            "Quel est le rôle principal d’une clause anti-dilution dans un term sheet ?",
            (
                "Ajuster la protection économique d’un investisseur si un tour ultérieur est réalisé à un prix inférieur.",
                "Empêcher toute émission future d’actions, y compris aux salariés.",
                "Garantir que la valeur de l’entreprise ne baisse jamais.",
                "Remplacer automatiquement une préférence de liquidation par des actions ordinaires.",
            ), 0, "anti-dilution protection down round weighted average conversion price",
            "La protection anti-dilution ajuste généralement le prix de conversion selon les termes négociés lors d’un tour à la baisse. Elle ne supprime pas toute dilution.",
        ),
        _QuestionSeed(
            "Avec une convertible note dotée d’un valuation cap et d’un discount, quel prix de conversion sert habituellement l’investisseur ?",
            (
                "Le prix le plus favorable entre celui issu du cap et celui issu du discount, selon les termes du contrat.",
                "Toujours le prix le plus élevé des deux.",
                "Le prix de l’action ordinaire à la sortie, sans tenir compte du tour qualifié.",
                "Aucun prix : la note ne peut jamais se convertir en equity.",
            ), 0, "convertible note valuation cap discount conversion price lower price",
            "Le cap et le discount donnent deux méthodes de conversion. Le contrat précise leur application, souvent en retenant le prix qui donne davantage d’actions à l’investisseur.",
        ),
    ),
    "TOPIC 5": (
        _QuestionSeed(
            "À quoi servent principalement les droits de gouvernance et de suivi du VC ?",
            (
                "Suivre l’entreprise, obtenir l’information prévue et participer aux décisions réservées convenues.",
                "Garantir au VC la gestion quotidienne de toutes les équipes.",
                "Remplacer les obligations d’information des fondateurs par un rendement garanti.",
                "Éviter toute discussion sur la stratégie de sortie.",
            ), 0, "board governance monitoring information rights reserved matters venture capital",
            "Le cours décrit le monitoring, l’accès à l’information et les droits de décision du conseil ou des investisseurs selon les accords conclus.",
        ),
        _QuestionSeed(
            "Pourquoi un fonds VC doit-il préparer une stratégie de sortie ?",
            (
                "La sortie permet de réaliser et distribuer les retours aux investisseurs du fonds.",
                "Elle fixe automatiquement la valorisation de chaque tour précédent.",
                "Elle élimine le besoin de gouvernance avant l’exit.",
                "Elle garantit que chaque startup sera vendue par IPO.",
            ), 0, "exit strategies venture capital return proceeds limited partners IPO trade sale",
            "Les sorties, par exemple vente industrielle ou IPO lorsque cela convient, réalisent la valeur et permettent au fonds de retourner les produits aux LPs.",
        ),
    ),
}


class QuizEngine:
    def __init__(self, index: CorpusIndex, db_path: str | Path):
        self.index = index
        self._lock = RLock()
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, question_id TEXT NOT NULL, chapter TEXT NOT NULL,
                correct INTEGER NOT NULL, difficulty TEXT NOT NULL
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS quiz_questions (
                question_id TEXT PRIMARY KEY, chapter TEXT NOT NULL, prompt TEXT NOT NULL, options_json TEXT NOT NULL,
                correct_index INTEGER NOT NULL, difficulty TEXT NOT NULL, citation_json TEXT NOT NULL
            )"""
        )
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(quiz_questions)")}
        if "explanation" not in columns:
            self._conn.execute("ALTER TABLE quiz_questions ADD COLUMN explanation TEXT NOT NULL DEFAULT ''")
        self._conn.commit()

    @_sqlite_locked
    def close(self) -> None:
        self._conn.close()

    @_sqlite_locked
    def _mastery_row(self, chapter: str) -> tuple[int, int]:
        chapter = self._canonical_chapter(chapter)
        row = self._conn.execute("SELECT COUNT(*) total, SUM(correct) correct FROM quiz_attempts WHERE chapter = ?", (chapter,)).fetchone()
        return int(row["total"] or 0), int(row["correct"] or 0)

    @_sqlite_locked
    def mastery(self, chapter: str) -> dict[str, Any]:
        chapter = self._canonical_chapter(chapter)
        total, correct = self._mastery_row(chapter)
        attempts_required = len(_QUESTION_BANK.get(chapter, ())) or 2
        return {
            "chapter": chapter,
            "attempts": total,
            "correct": correct,
            "attempts_required": attempts_required,
            "score": round(correct / total, 4) if total else 0.0,
            "mastered": bool(total >= attempts_required and correct / total >= 0.8),
        }

    @_sqlite_locked
    def difficulty(self, chapter: str) -> str:
        score = self.mastery(chapter)["score"]
        return "foundation" if score < 0.5 else "consolidation" if score < 0.8 else "challenge"

    @staticmethod
    def _answer_sentence(text: str) -> str:
        value = re.split(r"(?<=[.!?])\s+|\n+", text.strip())[0].strip()
        return value[:600]

    @staticmethod
    def _canonical_chapter(chapter: str) -> str:
        match = re.match(r"^\s*topic\s*(\d+)\b", str(chapter), re.IGNORECASE)
        return f"TOPIC {match.group(1)}" if match else str(chapter).strip()

    @_sqlite_locked
    def next_question(self, chapter: str, *, difficulty: str | None = None, sequence: int = 0) -> QuizQuestion | None:
        chapter = self._canonical_chapter(str(chapter or "").strip())
        if not chapter:
            return None
        chosen_difficulty = difficulty or self.difficulty(chapter)
        section_hits = self.index.chunks_for_section(chapter)
        if chapter.lower().startswith(("topic ", "chapter ", "section ")) and not section_hits:
            return None
        attempts = self._conn.execute("SELECT COUNT(*) FROM quiz_attempts WHERE chapter = ?", (chapter,)).fetchone()[0]
        seeds = _QUESTION_BANK.get(chapter)
        if seeds:
            seed = seeds[(int(attempts) + max(0, sequence)) % len(seeds)]
            hits = self.index.search(seed.citation_query, limit=20)
            chapter_number = re.search(r"\d+", chapter)
            topic_token = chapter_number.group(0) if chapter_number else ""
            topic_files = [
                hit for hit in hits
                if topic_token and re.search(rf"topic[_ -]?{topic_token}(?:[_ -]|\.|$)", Path(hit.source_path).name, re.IGNORECASE)
            ]
            topic_sections = [hit for hit in hits if chapter_number and re.search(rf"\btopic\s*{topic_token}\b", hit.section, re.IGNORECASE)]
            source_hint = seed.citation_source_contains.casefold()
            hinted_hits = [hit for hit in hits if source_hint and source_hint in Path(hit.source_path).name.casefold()]
            chunk = (hinted_hits or topic_files or topic_sections or hits)[0] if hits else None
            if chunk is None:
                return None
            options = list(seed.options)
            digest = hashlib.sha256(f"{chapter}:{attempts}:{sequence}:{seed.prompt}:{chosen_difficulty}".encode()).hexdigest()[:24]
            offset = int(digest[:2], 16) % len(options)
            rotated = options[offset:] + options[:offset]
            question = QuizQuestion(digest, chapter, seed.prompt, rotated, (seed.correct_index - offset) % len(options), chosen_difficulty, chunk.citation(), seed.explanation)
            self._save_question(question)
            return question
        chunks = section_hits[:8] if section_hits else self.index.search(chapter, limit=8)
        if not chunks:
            return None
        chunk = chunks[int(attempts) % len(chunks)]
        answer = self._answer_sentence(chunk.text)
        distractors = list(dict.fromkeys(self._answer_sentence(item.text) for item in chunks if item.chunk_id != chunk.chunk_id))
        options = [answer] + [item for item in distractors if item and item != answer][:2]
        fillers = ["Cette affirmation n’est pas soutenue par l’extrait consulté.", "L’extrait ne permet pas de conclure cela."]
        for filler in fillers:
            if len(options) >= 3:
                break
            options.append(filler)
        digest = hashlib.sha256(f"{chapter}:{chunk.chunk_id}:{attempts}:{chosen_difficulty}".encode()).hexdigest()[:24]
        # Deterministic rotation keeps tests and offline sessions reproducible while
        # preventing the correct answer from always being displayed first.
        offset = int(digest[:2], 16) % len(options)
        rotated = options[offset:] + options[:offset]
        question = QuizQuestion(digest, chapter, f"Quel énoncé est directement soutenu par le cours pour « {chapter} » ?", rotated, rotated.index(answer), chosen_difficulty, chunk.citation(), "Relis l’extrait cité et identifie le passage qui établit directement cette affirmation.")
        self._save_question(question)
        return question

    @_sqlite_locked
    def _save_question(self, question: QuizQuestion) -> None:
        self._conn.execute("INSERT OR REPLACE INTO quiz_questions(question_id,chapter,prompt,options_json,correct_index,difficulty,citation_json,explanation) VALUES(?,?,?,?,?,?,?,?)", (question.question_id, question.chapter, question.prompt, json.dumps(question.options, ensure_ascii=False), question.correct_index, question.difficulty, json.dumps(question.citation, ensure_ascii=False), question.explanation))
        self._conn.commit()

    @_sqlite_locked
    def answer(self, question_id: str, option_index: int) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM quiz_questions WHERE question_id = ?", (question_id,)).fetchone()
        if row is None:
            raise KeyError("Question de quiz introuvable dans la session locale.")
        options = json.loads(row["options_json"])
        if not isinstance(option_index, int) or not 0 <= option_index < len(options):
            raise ValueError("Réponse de quiz invalide.")
        correct = option_index == int(row["correct_index"])
        self._conn.execute("INSERT INTO quiz_attempts(question_id,chapter,correct,difficulty) VALUES(?,?,?,?)", (question_id, row["chapter"], int(correct), row["difficulty"]))
        self._conn.commit()
        return {
            "question_id": question_id,
            "correct": correct,
            "feedback": "Bonne réponse." if correct else "Pas encore. Compare ton choix à la correction et à la source.",
            "correct_answer": options[int(row["correct_index"])],
            "explanation": row["explanation"],
            "citation": json.loads(row["citation_json"]),
            "mastery": self.mastery(row["chapter"]),
            "local_only": True,
        }

    @_sqlite_locked
    def all_mastery(self, chapters: list[str]) -> list[dict[str, Any]]:
        return [self.mastery(chapter) for chapter in chapters]

    @_sqlite_locked
    def dashboard(self, chapters: list[str]) -> dict[str, Any]:
        notions = self.all_mastery(chapters)
        weak_points = sorted(
            (item for item in notions if not item["mastered"]),
            key=lambda item: (item["score"], item["attempts"], item["chapter"]),
        )
        return {
            "notions": notions,
            "weak_points": weak_points,
            "mastered_count": sum(1 for item in notions if item["mastered"]),
            "total_count": len(notions),
            "overall_score": round(sum(item["score"] for item in notions) / len(notions), 4) if notions else 0.0,
            "local_only": True,
        }


__all__ = ["QuizEngine", "QuizQuestion"]
