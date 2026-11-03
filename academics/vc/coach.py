"""VC Coach - English-focused calculation/debugging coach using Kilo CLI"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


COURSES_DIR = Path("/Users/comedelavenne/AI-Excel-Agent/docs/vc_study")
MISTAKES_FILE = Path.home() / ".nage" / "vc" / "mistakes.json"


class VCCoach:
    def __init__(self):
        self.mistakes_file = MISTAKES_FILE
        self.mistakes_file.parent.mkdir(parents=True, exist_ok=True)
        self.load_mistakes()

    def load_mistakes(self):
        if self.mistakes_file.exists():
            try:
                self.mistakes = json.loads(self.mistakes_file.read_text(encoding="utf-8"))
            except Exception:
                self.mistakes = []
        else:
            self.mistakes = []

    def save_mistake(self, entry: dict[str, Any]):
        entry["timestamp"] = datetime.now().isoformat()
        self.mistakes.append(entry)
        try:
            self.mistakes_file.write_text(json.dumps(self.mistakes, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def get_context(self, query: str, max_chars: int = 6000) -> str:
        if not COURSES_DIR.exists():
            return ""
        keywords = [w.lower() for w in re.split(r"[^a-zA-Z]+", query) if len(w) > 3]
        priority = ["pre-money", "post-money", "dilution", "liquidation", "preference", "waterfall", "cap table", "term sheet", "anti-dilution", "convertible", "irr", "moic", "vc method"]
        files = []
        for f in COURSES_DIR.glob("*.txt"):
            name_lower = f.name.lower()
            score = 0
            if any(p in name_lower for p in priority):
                score += 10
            for k in keywords:
                if k in name_lower:
                    score += 5
            files.append((score, f))
        files.sort(reverse=True)
        parts = []
        total = 0
        for score, f in files[:12]:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                chunk = content[:2000]
                if total + len(chunk) <= max_chars:
                    parts.append(f"=== {f.name} ===\n{chunk}\n")
                    total += len(chunk)
            except Exception:
                continue
        return "\n".join(parts)[:max_chars]

    def get_mistakes_context(self, limit: int = 10) -> str:
        if not self.mistakes:
            return ""
        recent = self.mistakes[-limit:]
        lines = ["RECENT MISTAKES TO LEARN FROM:"]
        for m in recent:
            lines.append(f"- Q:{m.get('question_id','?')} | Topic:{m.get('topic','?')} | Your:{m.get('your_answer','?')} | Correct:{m.get('correct_answer','?')} | Type:{m.get('error_type','?')}")
        return "\n".join(lines)

    def build_prompt(self, mode: str, question: str, user_answer: str = None, hint: bool = False) -> str:
        ctx = self.get_context(question)
        mistakes_ctx = self.get_mistakes_context()
        
        system = """You are an elite EDHEC Venture Capital tutor coaching for the exam in English.

CORE PRINCIPLES:
- ALWAYS answer in English
- Be Socratic: guide the student to think, don't dump the full solution immediately
- Base strictly on the course materials provided
- For ALL calculations: use this exact structure: FORMULA -> GIVEN DATA -> STEP BY STEP -> VERIFICATION -> COMMON TRAPS
- Focus on pre-money/post-money, dilution, cap table, liquidation preferences (1x non-participating vs participating), anti-dilution, convertibles, waterfalls, IRR/MOIC
- Use precise EDHEC VC terminology
- Distinguish conceptual errors from arithmetic errors
- Make the student do the reasoning"""

        if mode == "debug":
            instruction = """MODE: CALCULATION DEBUG
The student got this wrong or needs to debug it.

Your job:
1. Don't just solve it. First, ask them to identify what they did step by step
2. Force them to write down: formula used, numbers used, logic
3. Spot the exact error (wrong formula, wrong denominator, confusion pre/post-money, dilution calc mistake, etc.)
4. Walk them to the fix WITHOUT giving the final number until they've reasoned through
5. Make them redo it themselves after understanding
6. Show verification method"""

        elif mode == "explain":
            instruction = """MODE: CONCEPT EXPLANATION
Explain this VC concept clearly for exam prep.
Use examples from course logic, not generic internet definitions.
Connect to calculations where relevant.
Test understanding with 1-2 questions."""

        elif mode == "drill":
            instruction = """MODE: SOCRATIC DRILL
Give ONE question based on their weak areas.
Don't give answer. Give hints only if they ask or struggle.
Force them to show their working.
After they answer, debug properly."""

        else:
            instruction = """MODE: COACH
Help them think through this properly for the EDHEC exam."""

        if hint:
            instruction += "\n\nGIVE ONLY A HINT. Do NOT give the full solution. Point them in the right direction."

        prompt = f"""{instruction}

QUESTION/TOPIC:
{question}

STUDENT'S ATTEMPT/ANSWER:
{user_answer or "Not provided yet - help me think through this"}

{mistakes_ctx}

COURSE MATERIAL EXTRACTS:
{ctx}

Remember: Train them to solve it themselves. Be strict but constructive. All in English."""
        return f"{system}\n\n{prompt}"

    def run(self, mode: str, question: str, user_answer: str = None, hint: bool = False) -> str:
        prompt = self.build_prompt(mode, question, user_answer, hint)
        # Use kilo run via shell
        try:
            cmd = f"printf '%s' {shlex.quote(prompt)} | kilo run 2>&1"
            r = subprocess.run(cmd, cwd="/Users/comedelavenne/AI-Excel-Agent", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
            if r.returncode == 0 and r.stdout:
                out = r.stdout.decode("utf-8", errors="ignore")
                # clean ANSI and headers
                out_clean = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', out)
                cleaned = []
                for l in out_clean.splitlines():
                    ls = l.strip()
                    if not ls:
                        continue
                    if ls.startswith('>'):
                        continue
                    if ls.startswith('code ·'):
                        continue
                    if ls.startswith('╭') or ls.startswith('╰') or ls.startswith('│'):
                        continue
                    if ls.startswith('kilo'):
                        continue
                    if ls.startswith('INFO'):
                        continue
                    if ls.startswith('service='):
                        continue
                    if ls.startswith('version='):
                        continue
                    cleaned.append(l.rstrip())
                result = '\n'.join(cleaned).strip()
                if len(result) > 80:
                    return result
        except Exception as e:
            return f"Error calling kilo: {e}"
        return "Failed to get response from kilo. Make sure kilo CLI is working."
