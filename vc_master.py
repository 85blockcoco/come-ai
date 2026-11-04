#!/usr/bin/env python3
"""VC Master - Unified exam preparation system for EDHEC VC exam (English)."""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from academics.vc.storage import DEFAULT_SETTINGS, default_vc_home

DEFAULT_EXAM_SETTINGS = {
    key: DEFAULT_SETTINGS[key]
    for key in ("exam_date", "exam_time", "exam_duration_minutes")
}


def vc_home() -> Path:
    """Return the same local VC home as ``academics.vc.storage``."""
    return default_vc_home()


class VCMaster:
    def __init__(self):
        self.base = Path(__file__).resolve().parent
        self.courses_dir = self.base / "docs/vc_study"
        self.data_dir = Path.home() / ".nage/vc_master"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.courses = {}
        if self.courses_dir.is_dir():
            for path in self.courses_dir.glob("*.txt"):
                self.courses[path.stem] = path.read_text(encoding="utf-8", errors="ignore")
        self.progress_file = self.data_dir / "progress.json"
        self.load_progress()

    def load_progress(self):
        if self.progress_file.exists():
            try:
                payload = json.loads(self.progress_file.read_text(encoding="utf-8"))
                self.progress = payload if isinstance(payload, dict) else {}
            except (OSError, json.JSONDecodeError):
                self.progress = {}
        else:
            self.progress = {
                "started": datetime.now().isoformat(),
                "exam_date": None,
                "cards": {},
                "weak_topics": [],
                "total_time_minutes": 0,
            }

    def save_progress(self):
        self.progress_file.write_text(
            json.dumps(self.progress, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def load_exam_settings(self):
        """Read the deterministic VC settings, with a safe legacy fallback."""
        settings = dict(DEFAULT_EXAM_SETTINGS)
        path = vc_home() / "settings.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    settings.update(payload)
            except (OSError, json.JSONDecodeError):
                pass
        # ``vc_master`` used to store its own, sometimes wrong, date. The
        # deterministic settings now win so the displayed date cannot drift.
        if not settings.get("exam_date"):
            settings["exam_date"] = self.progress.get("exam_date")
        return settings

    def save_exam_settings(self, exam_date, exam_time, duration_minutes=90):
        path = vc_home() / "settings.json"
        settings = self.load_exam_settings()
        settings.update(
            {
                "exam_date": exam_date,
                "exam_time": exam_time,
                "exam_duration_minutes": int(duration_minutes),
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name("settings.json.tmp")
        temporary.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def status(self):
        settings = self.load_exam_settings()
        exam_date = settings.get("exam_date")
        exam_time = settings.get("exam_time", "16:00")
        duration = settings.get("exam_duration_minutes", 90)
        days_left = "?"
        exam_label = "Set with: vc master set-exam YYYY-MM-DD [HH:MM]"
        if exam_date:
            try:
                exam_dt = datetime.fromisoformat(f"{exam_date}T{exam_time}")
                days_left = max(0, (exam_dt.date() - date.today()).days)
                exam_label = f"{exam_date} {exam_time} ({duration} min) - {days_left} days left"
            except ValueError:
                exam_label = f"{exam_date} (invalid date/time; fix with: vc master set-exam)"
        print("=" * 65)
        print("VC MASTER - EDHEC VC Exam Prep (English) | Based on YOUR courses")
        print("=" * 65)
        print(
            f"\nCourses loaded: {len(self.courses)} files "
            f"({sum(len(v) for v in self.courses.values()):,} chars)"
        )
        try:
            from academics.vc.content import load_content

            content = load_content()
            print(
                "Deterministic engine: "
                f"{len(content.topics)} topics, {len(content.cards)} cards, "
                f"{len(content.drills)} drills, {len(content.cases)} cases, "
                f"{len(content.glossary)} glossary entries"
            )
        except Exception:
            pass
        print(f"Exam: {exam_label}")
        print(
            "Cards mastered: "
            f"{sum(1 for c in self.progress.get('cards', {}).values() if c.get('m', 0) >= 3)}"
            f"/{len(self.progress.get('cards', {}))}"
        )
        print(f"Time studied: {self.progress.get('total_time_minutes', 0)} min")
        print("\n" + "=" * 65)
        print("COMMANDS:")
        print("  vc master set-exam DATE [HH:MM] - Set the exam date/time")
        print("  vc master sprint [hours]  - Smart sprint plan for Friday")
        print("  vc master formulas        - Drill pre-money/post-money/dilution/waterfall")
        print("  vc master terms           - Term sheet clauses practice")
        print("  vc master cases           - Practice with your course cases")
        print("  vc master revise          - Focus on weak areas")
        print("  vc master simulate [min]  - Timed exam simulation")
        print("=" * 65)

    def set_exam(self, exam_date, exam_time="16:00", duration_minutes=90):
        try:
            date.fromisoformat(exam_date)
        except ValueError as error:
            raise ValueError(f"date attendue au format AAAA-MM-JJ : {exam_date!r}") from error
        try:
            datetime.strptime(exam_time, "%H:%M")
        except ValueError as error:
            raise ValueError(f"heure attendue au format HH:MM : {exam_time!r}") from error
        self.progress["exam_date"] = exam_date
        self.save_progress()
        self.save_exam_settings(exam_date, exam_time, duration_minutes)
        days = max(0, (date.fromisoformat(exam_date) - date.today()).days)
        print(
            f"Exam set for {exam_date} {exam_time} ({duration_minutes} min) - "
            f"{days} days to go."
        )

    def formulas(self):
        print("=" * 65)
        print("FORMULA DRILLS - Pre-money/Post-money/Ownership/Dilution")
        print("=" * 65)
        drills = [
            ("1", "A VC invests €3M for 25% on a post-money basis. What is pre-money?", "Pre-money = Post-money - I = (3/0.25) - 3 = 9M€", "Post-money = I/% = 12M€, Pre-money = 9M€"),
            ("2", "Pre-money €8M, invest €2M. Post-money and investor ownership?", "Post-money €10M, 20%", "Post-money = Pre + I = 10M€, % = 2/10 = 20%"),
            ("3", "Post-money €20M, investor gets 15%. Amount invested?", "€3M", "I = Post-money * % = 20M * 15% = 3M"),
            ("4", "Company has 1M shares, pre-money value €5M, VC invests €1M for new shares at pre-money price. How many shares? Ownership?", "Price €5, 200k shares, 16.67%", "P = 5M/1M=€5, shares = 1M/5=200k, ownership = 200k/1.2M = 1/6"),
            ("5", "1x non-participating preference, invested €5M, exit €15M. How much does VC get if converts?", "€5M vs €3.75M -> takes €5M or convert to 25% of €15M=€3.75M? Wait - 1x non-participating: can take preference OR convert. Compare.", "Depends: if 1x non-participating, VC takes max(preference, pro-rata share). 25% of 15M = 3.75M < 5M so takes 5M"),
        ]
        for num, question, answer, explanation in drills:
            print(f"\nDRILL {num}: {question}")
            print(f"  Answer: {answer}")
            print(f"  Explanation: {explanation}")
        print("\n" + "=" * 65)
        print("Practice with: python nage.py vc drill random")
        print("=" * 65)

    def terms(self):
        print("=" * 65)
        print("TERM SHEET CLAUSES - Must Know for Exam")
        print("=" * 65)
        clauses = [
            ("Liquidation Preference", "Order of payout on exit/liquidation. 1x vs multiple, participating vs non-participating"),
            ("Anti-dilution", "Protection if down round. Full ratchet vs weighted average (broad/narrow based)"),
            ("Pre-emption rights / Pro-rata", "Right to invest in future rounds to maintain %"),
            ("Vesting", "Founder shares vest over time, usually 4 years with 1-year cliff"),
            ("Drag-along / Tag-along", "Drag = force minority to sell; Tag = minority can join sale"),
            ("ESOP / Option pool", "Often created pre-money -> dilutes existing shareholders"),
            ("Redemption rights", "Rare in VC, more PE"),
            ("Pay-to-play", "In down rounds, must invest to keep preferences"),
        ]
        for name, description in clauses:
            print(f"\n• {name}")
            print(f"  {description}")
        print("\n" + "=" * 65)
        print("Practice with: python nage.py vc glossary search liquidation")
        print("=" * 65)

    def cases(self):
        print("=" * 65)
        print("CASES FROM THE DETERMINISTIC ENGINE")
        print("=" * 65)
        try:
            from academics.vc.content import load_content

            content = load_content()
            for case in content.cases:
                print(f"  • {case.id} — {case.title} (topic {case.topic_id}, difficulty {case.difficulty})")
        except Exception as error:
            print(f"  (engine unavailable: {error})")
        print("\nPractice with:")
        print("  python nage.py vc case list")
        print("  python nage.py vc case show VC03-CASE01")
        print("=" * 65)

    def simulate(self, minutes=60):
        minutes = max(1, int(minutes))
        print("=" * 65)
        print(f"EXAM SIMULATION - {minutes} MINUTES (Timed)")
        print("=" * 65)
        if minutes < 10:
            print("\nShort format:")
            print(f"  - {max(1, minutes - 2)} min: one calculation, no notes")
            print("  - 2 min: one definition, written from memory")
        else:
            part1 = max(1, round(minutes * 0.2))
            part2 = max(1, round(minutes * 0.4))
            part3 = max(1, minutes - part1 - part2)
            total = part1 + part2 + part3
            print("\nStructure adapted to the available time:")
            print(f"  Part 1: Theory/Definitions (~20%) - {part1} min")
            print(f"  Part 2: Valuation & Calculations (~40%) - {part2} min")
            print(f"  Part 3: Term Sheet/Case Analysis (~40%) - {part3} min")
            print(f"\nTotal: {total} minutes")
        print("\nStart now:")
        print("  python nage.py vc paper show 2025")
        print("  python nage.py vc exam start --questions 20 --minutes 90")
        print("=" * 65)

    def sprint(self, hours=3):
        hours = max(1, int(hours))
        print("=" * 65)
        print(f"SPRINT - {hours} hour(s) available")
        print("=" * 65)
        print("1. python nage.py vc formulas")
        print("2. python nage.py vc drill random --topic VC04 --answer \"...\"")
        print("3. python nage.py vc paper show 2025")
        print("4. python nage.py vc revise")
        print("=" * 65)

    def revise(self):
        print("=" * 65)
        print("TARGETED REVISION - Focus on High-Yield for Friday")
        print("=" * 65)
        print("\nPRIORITY 1 (Do first - 2-3 hours):")
        print("  1. Pre-money/post-money + ownership calculations")
        print("  2. Dilution mechanics")
        print("  3. Liquidation preferences (1x NP vs participating)")
        print("\nPRIORITY 2 (Next - 1-2 hours):")
        print("  4. Term sheet key clauses")
        print("  5. Anti-dilution (weighted average vs full ratchet)")
        print("  6. Down rounds")
        print("\nPRIORITY 3 (If time - 1 hour):")
        print("  7. IRR/MOIC basics")
        print("  8. Exit strategies")
        print("\nQuick start:")
        print("  python nage.py vc formulas && python nage.py vc drill random")
        print("=" * 65)


if __name__ == "__main__":
    master = VCMaster()
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    try:
        if command == "status":
            master.status()
        elif command == "set-exam":
            if len(sys.argv) < 3:
                raise ValueError("usage: vc_master.py set-exam AAAA-MM-JJ [HH:MM] [minutes]")
            exam_time = sys.argv[3] if len(sys.argv) > 3 else "16:00"
            duration = int(sys.argv[4]) if len(sys.argv) > 4 else 90
            master.set_exam(sys.argv[2], exam_time, duration)
        elif command == "formulas":
            master.formulas()
        elif command == "terms":
            master.terms()
        elif command == "cases":
            master.cases()
        elif command == "simulate":
            master.simulate(int(sys.argv[2]) if len(sys.argv) > 2 else 60)
        elif command == "revise":
            master.revise()
        elif command == "sprint":
            master.sprint(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
        else:
            master.status()
    except (ValueError, OSError) as error:
        print(f"Erreur : {error}", file=sys.stderr)
        raise SystemExit(2)
