"""VC Tutor - English-focused AI tutor for EDHEC VC exam.

Cloud calls are disabled by default.  Set ``VC_TUTOR_CLOUD=1`` (and, if
needed, ``VC_TUTOR_LOAD_ENV=1``) to opt in. Provider configuration stays
private to the tutor; loading a file never changes the process environment.
"""

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

_REPO_ROOT = Path(__file__).resolve().parent
_CENTRAL_PROVIDER_ENV = Path.home() / "Library" / "Application Support" / "NAGE" / "providers.env"
_PROJECT_ENV_FILENAMES = (".env", ".env.local")
_MAX_GEMINI_ATTEMPTS = 4
_CONFIG_NAMES = {
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEYS",
    "GEMINI_PRIMARY_MODEL",
    "MISTRAL_API_KEY",
    "MISTRAL_MODEL",
    "VC_TUTOR_CLOUD",
    "VC_TUTOR_LOAD_ENV",
    "VC_TUTOR_KILO",
    "VC_TUTOR_KILO_MODEL",
}


def _provider_setting(name: str) -> bool:
    return name in _CONFIG_NAMES or bool(re.fullmatch(r"GEMINI_API_KEY_?\d+", name))


def _truthy(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class VCTutor:
    def __init__(
        self,
        *,
        load_env: bool | None = None,
        cloud: bool | None = None,
        data_dir: Path | None = None,
        env_paths: Sequence[Path] | None = None,
        environ: Mapping[str, str] | None = None,
        kilo_fallback: Callable[[str, str | None], str | None] | None = None,
    ):
        # An explicitly offline, isolated application does not inspect provider
        # variables or the user's central configuration.
        explicit_env = environ if environ is not None else ({} if load_env is False and cloud is False else os.environ)
        self._provider_config = {name: str(value) for name, value in explicit_env.items() if _provider_setting(name)}
        self._env_paths = (
            tuple(env_paths) if env_paths is not None else (*(_REPO_ROOT / name for name in _PROJECT_ENV_FILENAMES), _CENTRAL_PROVIDER_ENV)
        )
        self.load_env_requested = (
            load_env
            if load_env is not None
            else (_truthy(self._provider_config.get("VC_TUTOR_LOAD_ENV")) or _truthy(self._provider_config.get("VC_TUTOR_CLOUD")))
        )
        if self.load_env_requested:
            self.load_env()
        self.cloud_enabled = cloud if cloud is not None else _truthy(self._provider_config.get("VC_TUTOR_CLOUD"))
        self._kilo_fallback = kilo_fallback
        self._last_provider = None
        self._last_model = None
        self._gemini_quota_exhausted = False
        self.courses_dir = _REPO_ROOT / "docs" / "vc_study"
        vc_home = (
            Path(data_dir).expanduser()
            if data_dir is not None
            else Path(os.environ.get("NAGE_VC_HOME", str(Path.home() / ".nage" / "vc"))).expanduser()
        )
        self.tutor_config_path = vc_home / "tutor_config.json"
        self.tutor_config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.load_config()
        self.config["cloud_enabled"] = self.cloud_enabled
        self.last_error = None

    def load_env(self):
        """Read only active provider settings, without exporting any variables.

        Later files override earlier files; explicitly supplied process values
        always win. Paths are injectable so tests never read the real files.
        """
        values = {}
        for env_path in self._env_paths:
            try:
                lines = Path(env_path).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for line in lines:
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:].lstrip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                name, value = name.strip(), value.strip()
                if not _provider_setting(name):
                    continue
                if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
                    value = value[1:-1]
                else:
                    value = value.split(" #", 1)[0].rstrip()
                values[name] = value
        self._provider_config = {**values, **self._provider_config}

    def _gemini_keys(self) -> list[str]:
        names = ["GEMINI_API_KEY"]
        names.extend(
            sorted(
                (name for name in self._provider_config if re.fullmatch(r"GEMINI_API_KEY_?\d+", name)),
                key=lambda name: (int(re.search(r"\d+$", name).group()), name),
            )
        )
        names.append("GOOGLE_API_KEY")
        candidates = [self._provider_config.get(name, "") for name in names]
        candidates.extend(self._provider_config.get("GEMINI_API_KEYS", "").split(","))
        return list(dict.fromkeys(key.strip() for key in candidates if key.strip()))

    def _redact(self, text: str) -> str:
        keys = self._gemini_keys() + [self._provider_config.get("MISTRAL_API_KEY", "")]
        for key in sorted(filter(None, keys), key=len, reverse=True):
            text = text.replace(key, "[redacted]")
        return text

    def _gemini_model(self) -> str:
        model = self._provider_config.get("GEMINI_PRIMARY_MODEL", "gemini-3.1-flash-lite")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model) or model in self._gemini_keys():
            return "gemini-3.1-flash-lite"
        return self._redact(model)

    def load_config(self):
        default = {
            "enabled": True,
            "mode": "hybrid",
            "prefer_reasoning": True,
            "max_context_chars": 10000,
            "ollama_model": "qwen3.5:4b",
            "ollama_host": "http://localhost:11434",
            "cloud_enabled": False,
        }
        if self.tutor_config_path.exists():
            try:
                self.config = {**default, **json.loads(self.tutor_config_path.read_text())}
            except Exception:
                self.config = default
        else:
            self.config = default
            try:
                self.tutor_config_path.write_text(json.dumps(self.config, indent=2))
            except Exception:
                pass

    def get_relevant_context(self, query: str, max_chars: int = 10000) -> str:
        keywords = [w.lower() for w in query.split() if len(w) > 2]
        if not keywords:
            return ""
        priority = ["Topic", "Session", "Background note", "Case", "Term sheet", "Liquidation", "Pre-money", "Post-money"]

        files = []
        try:
            files = sorted(self.courses_dir.glob("*.txt"), key=lambda x: x.name)
        except Exception:
            files = []

        file_chunks = []
        df = {k: 0 for k in keywords}
        for txt_file in files:
            try:
                content = txt_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lines_list = content.splitlines()
            chunk_size = 40
            chunks = []
            for start in range(0, len(lines_list), chunk_size):
                end = min(start + chunk_size, len(lines_list))
                text = "\n".join(lines_list[start:end])
                if not text.strip():
                    continue
                chunks.append((start + 1, end, text))
                lowered = text.lower()
                for k in keywords:
                    if k in lowered:
                        df[k] += 1
            file_chunks.append((txt_file, chunks))

        n_chunks = max(1, sum(len(fc[1]) for fc in file_chunks))
        avg_len = max(1.0, sum(len(t) for _, chunks in file_chunks for _, _, t in chunks) / n_chunks)
        k1 = 1.5
        b = 0.75
        scored = []
        for txt_file, chunks in file_chunks:
            for start, end, text in chunks:
                lowered = text.lower()
                doc_len = len(text)
                score = 0.0
                for k in keywords:
                    tf = lowered.count(k)
                    if tf == 0:
                        continue
                    idf = 1.0 + (n_chunks / (1 + df.get(k, 1)))
                    norm = tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avg_len))
                    score += norm * idf
                if any(p.lower() in txt_file.name.lower() for p in priority):
                    score += 0.5
                if score > 0:
                    scored.append((score, text, txt_file.name, start, end))

        scored.sort(key=lambda item: (-item[0], item[2], item[3]))
        context_parts = []
        total = 0
        for score, text, name, start, end in scored:
            block = f"=== {name} (lines {start}-{end}, score {score:.2f}) ===\n{text}\n"
            if total + len(block) > max_chars:
                continue
            context_parts.append(block)
            total += len(block)
            if total >= max_chars:
                break
        if not context_parts:
            for txt_file, chunks in file_chunks:
                if not any(p.lower() in txt_file.name.lower() for p in priority):
                    continue
                for start, end, text in chunks[:1]:
                    block = f"=== {txt_file.name} (lines {start}-{end}) ===\n{text[:1500]}\n"
                    if total + len(block) <= max_chars:
                        context_parts.append(block)
                        total += len(block)
        return "\n".join(context_parts)[:max_chars]

    def retrieve_passages(self, query: str, max_passages: int = 5) -> list[dict]:
        keywords = [w.lower() for w in query.split() if len(w) > 2]
        if not keywords:
            return []
        context = self.get_relevant_context(query, max_chars=100000)
        passages = []
        for block in context.split("\n\n"):
            if not block.strip():
                continue
            first_line = block.splitlines()[0] if block.splitlines() else ""
            passages.append({"citation": first_line.strip("= "), "text": block})
            if len(passages) >= max_passages:
                break
        return passages

    @staticmethod
    def local_ollama_host(value) -> str | None:
        try:
            url = urlsplit(str(value))
            if (
                url.scheme not in {"http", "https"}
                or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username is not None
                or url.password is not None
                or url.path not in {"", "/"}
                or url.query
                or url.fragment
            ):
                return None
            _ = url.port  # Reject malformed or out-of-range ports before any I/O.
            return str(value).rstrip("/")
        except (TypeError, ValueError):
            return None

    def call_ollama(self, prompt: str, system: str = None) -> str:
        try:
            import httpx

            host = self.local_ollama_host(self.config.get("ollama_host", "http://localhost:11434"))
            if host is None:
                self.last_error = "The local tutor requires a loopback Ollama address."
                return None
            model = self.config.get("ollama_model", "qwen3.5:4b")
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            try:
                resp = httpx.post(
                    f"{host}/api/chat",
                    headers={"Content-Type": "application/json"},
                    json={"model": model, "messages": messages, "stream": False, "options": {"temperature": 0.1, "num_predict": 1024}},
                    timeout=120,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("message", {}).get("content", "") or ""
                    if content.strip():
                        return self._redact(content.strip())
            except Exception:
                pass
            try:
                resp = httpx.post(
                    f"{host}/v1/chat/completions",
                    headers={"Content-Type": "application/json"},
                    json={"model": model, "messages": messages, "temperature": 0.1, "max_tokens": 1024, "stream": False},
                    timeout=120,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
                    if content.strip():
                        return self._redact(content.strip())
            except Exception:
                pass
        except Exception:
            pass
        return None

    def call_mistral(self, prompt: str, system: str = None) -> str:
        if not self.config.get("cloud_enabled"):
            return None
        try:
            import httpx

            key = self._provider_config.get("MISTRAL_API_KEY")
            if not key:
                return None
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = httpx.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "mistral-small-latest", "messages": messages, "temperature": 0.1, "max_tokens": 4096},
                timeout=180,
            )
            if resp.status_code == 200:
                return self._redact(resp.json()["choices"][0]["message"]["content"])
            return None
        except Exception:
            return None

    def call_kilo(self, prompt: str, system: str = None) -> str | None:
        """Controlled extension point, never a shell or an unverified CLI call.

        Only the exhausted Gemini pool invokes this hook. The adapter requires
        an explicitly configured model; tests may inject a synthetic callable.
        """
        if not (self.config.get("cloud_enabled") and _truthy(self._provider_config.get("VC_TUTOR_KILO")) and self._gemini_quota_exhausted):
            return None
        try:
            if self._kilo_fallback is not None:
                result = self._kilo_fallback(prompt, system)
            else:
                model = self._provider_config.get("VC_TUTOR_KILO_MODEL")
                if not model:
                    return None
                from academics.vc.kilo_tutor import run_kilo_tutor

                result = run_kilo_tutor(prompt, system=system, model=model, timeout=90)
            if result and isinstance(result, str):
                self.last_error = None
                self._last_provider = "kilo"
                self._last_model = self._redact(self._provider_config.get("VC_TUTOR_KILO_MODEL", "kilo"))
                return self._redact(result)
        except Exception:
            self.last_error = "Kilo fallback unavailable."
        return None

    @staticmethod
    def _quota_response(response) -> bool:
        if response.status_code == 429:
            return True
        if response.status_code == 400:
            try:
                return response.json().get("error", {}).get("status") == "RESOURCE_EXHAUSTED"
            except (ValueError, AttributeError, TypeError):
                pass
        return False

    def call_gemini(self, prompt: str, system: str = None) -> str:
        if not self.config.get("cloud_enabled"):
            return None
        self.last_error = None
        self._last_provider = None
        self._last_model = None
        self._gemini_quota_exhausted = False
        keys = self._gemini_keys()
        if not keys:
            self.last_error = "Gemini has no configured key."
            return None
        model = self._gemini_model()
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        try:
            import httpx

            for key in keys[:_MAX_GEMINI_ATTEMPTS]:
                # The key is a header, never part of a URL or public error.
                resp = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": full_prompt}]}],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096},
                    },
                    timeout=180,
                )
                if resp.status_code == 200:
                    try:
                        result = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                        if not isinstance(result, str) or not result.strip():
                            raise ValueError
                    except (KeyError, IndexError, TypeError, ValueError):
                        self.last_error = "Gemini returned an empty or invalid answer."
                        return None
                    self.last_error = None
                    self._last_provider = "gemini"
                    self._last_model = model
                    return self._redact(result)
                if self._quota_response(resp):
                    self.last_error = "Gemini quota exhausted."
                    continue
                reasons = {
                    400: "invalid request",
                    401: "authentication rejected",
                    402: "billing limit reached",
                    403: "access denied",
                    404: "model unavailable",
                }
                reason = reasons.get(resp.status_code, "service unavailable" if resp.status_code >= 500 else "request rejected")
                self.last_error = f"Gemini {reason}."
                return None
        except Exception:
            self.last_error = "Gemini unreachable."
            return None
        if len(keys) > _MAX_GEMINI_ATTEMPTS:
            self.last_error = "Gemini attempt limit reached; untried keys remain."
            return None
        # Every configured Gemini key exhausted a recognized quota. Other
        # failures never authorize a metered fallback.
        self._gemini_quota_exhausted = True
        if _truthy(self._provider_config.get("VC_TUTOR_KILO")):
            return self.call_kilo(prompt, system)
        return None

    def provider_status(self) -> dict:
        """Provider names, key counts and bounded errors; never credentials."""
        key_count = len(self._gemini_keys())
        status = {
            "cloud_enabled": bool(self.config.get("cloud_enabled")),
            "gemini_key_present": bool(key_count),
            "gemini_key_count": key_count,
            "gemini_model": self._gemini_model(),
            "mistral_key_present": bool(self._provider_config.get("MISTRAL_API_KEY")),
            "mistral_key_count": int(bool(self._provider_config.get("MISTRAL_API_KEY"))),
            "kilo_enabled": bool(self.config.get("cloud_enabled")) and _truthy(self._provider_config.get("VC_TUTOR_KILO")),
            "kilo_configured": self._kilo_fallback is not None or bool(self._provider_config.get("VC_TUTOR_KILO_MODEL")),
            "ollama_host": self.local_ollama_host(self.config.get("ollama_host")),
            "last_error": self._redact(getattr(self, "last_error", None) or "") or None,
            "last_provider": self._last_provider,
        }
        if status["cloud_enabled"] and key_count:
            status["mode"] = "gemini"
        elif status["cloud_enabled"]:
            status["mode"] = "degraded"
        else:
            status["mode"] = "offline"
        return status

    def tutor_explain(self, question: str, user_answer: str = None) -> str:
        system = """You are an extremely demanding but highly effective EDHEC Business School Venture Capital professor preparing a student for a high-level English exam.

STRICT RULES:
- ALWAYS respond in English. No French.
- Give a DIRECT answer first (explanation + example if relevant), then guide with questions if helpful.
- Be precise on formulas, units, and financial conventions.
- Challenge the student's reasoning when needed.
- Cite the course context when possible.
- Do not invent sources or formulas.
"""
        prompt = question
        if user_answer:
            prompt = f"Question: {question}\nStudent's answer: {user_answer}\nExplain and correct if needed."
        context = self.get_relevant_context(question, max_chars=6000)
        if context:
            prompt = f"Course context:\n{context}\n\n{prompt}"
        for provider in ["gemini", "ollama"]:
            if provider == "gemini":
                result = self.call_gemini(prompt, system)
            elif provider == "ollama":
                result = self.call_ollama(prompt, system)
            if result:
                return result
        return "No model available. Check your API configuration or start Ollama."

    def debug_formula(self, question: str) -> str:
        system = """You are an EDHEC VC professor. Debug the student's formula or calculation.
- Explain the correct formula step by step.
- Identify common mistakes.
- Provide a worked example.
- Always in English."""
        prompt = f"Debug this formula/calculation: {question}"
        context = self.get_relevant_context(question, max_chars=4000)
        if context:
            prompt = f"Course context:\n{context}\n\n{prompt}"
        for provider in ["gemini", "ollama"]:
            if provider == "gemini":
                result = self.call_gemini(prompt, system)
            elif provider == "ollama":
                result = self.call_ollama(prompt, system)
            if result:
                return result
        return "No model available."

    def oral_sim(self, topic: str) -> str:
        system = """You are an EDHEC VC oral examiner. Ask the student a question, then evaluate their answer.
- Ask one question at a time.
- Provide feedback and a follow-up.
- Always in English."""
        prompt = f"Generate an oral exam question on: {topic}"
        context = self.get_relevant_context(topic, max_chars=4000)
        if context:
            prompt = f"Course context:\n{context}\n\n{prompt}"
        for provider in ["gemini", "ollama"]:
            if provider == "gemini":
                result = self.call_gemini(prompt, system)
            elif provider == "ollama":
                result = self.call_ollama(prompt, system)
            if result:
                return result
        return "No model available."

    def exam_prep(self, focus: str = None) -> str:
        system = """You are an EDHEC VC exam coach. Help the student prepare.
- Prioritize high-yield topics.
- Provide concise summaries and practice questions.
- Always in English."""
        prompt = "Prepare me for the VC exam."
        if focus:
            prompt = f"Focus on: {focus}"
        context = self.get_relevant_context(prompt, max_chars=4000)
        if context:
            prompt = f"Course context:\n{context}\n\n{prompt}"
        for provider in ["gemini", "ollama"]:
            if provider == "gemini":
                result = self.call_gemini(prompt, system)
            elif provider == "ollama":
                result = self.call_ollama(prompt, system)
            if result:
                return result
        return "No model available."

    # ------------------------------------------------------------------ #
    # Pedagogical tutor (Mission 3): adaptive, hint-first, mastery-aware
    # ------------------------------------------------------------------ #

    TUTOR_MODES = ("explain", "hint", "socratic", "analogy", "correct", "deep")

    _MODE_INSTRUCTIONS = {
        "explain": (
            "Give a clear, complete explanation of the concept. Start with the direct "
            "answer, then the intuition, then a short worked example. End with ONE "
            "check-your-understanding question."
        ),
        "hint": (
            "DO NOT give the final answer. Give the student a first hint: the relevant "
            "formula or principle, without substituting numbers. Then ask them to try. "
            "If they already tried, point out the exact step where they went wrong."
        ),
        "socratic": (
            "Do not answer directly. Ask guiding questions, one at a time, that lead the "
            "student to derive the answer themselves. Max 3 questions. Only confirm or "
            "correct after the student responds."
        ),
        "analogy": (
            "Propose a NEW analogous exercise with different numbers, on the same "
            "notion, exam-level difficulty. State it clearly with givens and the "
            "question. Do NOT solve it."
        ),
        "correct": (
            "The student submitted an answer. Evaluate it: say if it is right or wrong, "
            "explain WHY (the reasoning, not just the result), give the correct "
            "method step by step, and name the mistake category (formula, order, unit, "
            "missing data, convention)."
        ),
        "deep": (
            "Give a deep, exam-grade treatment: formal definition, formula with every "
            "variable defined, conventions (broad vs narrow based, participating vs "
            "not), common exam traps, and a full worked example with numbers."
        ),
    }

    def tutor_chat(
        self,
        message: str,
        *,
        mode: str = "explain",
        topic_id: str | None = None,
        mastery: dict | None = None,
        errors: list | None = None,
        student_answer: str | None = None,
        history: list | None = None,
    ) -> dict:
        """Adaptive tutoring turn. Returns a structured, citable result.

        The response always declares its provenance: ``source`` is
        "ai" for generated text, and ``passages`` lists the retrieved course
        excerpts the answer was grounded in (empty when none were found).
        """
        if mode not in self.TUTOR_MODES:
            mode = "explain"
        message = str(message or "").strip()
        if not message and not student_answer:
            return {
                "text": "Ask a question, submit an answer, or pick a mode (explain, hint, socratic, analogy, correct, deep).",
                "source": "offline",
                "mode": mode,
                "passages": [],
                "model": None,
            }

        parts = [f"[Mode: {mode}]"]
        if topic_id:
            parts.append(f"[Topic: {topic_id}]")
        if mastery:
            # Compact mastery summary: status, accuracy, weakest skills.
            status = mastery.get("status", "untested")
            accuracy = mastery.get("accuracy")
            attempts = mastery.get("attempts", 0)
            top_errors = mastery.get("top_errors") or []
            line = f"[Student mastery: {status}"
            if accuracy is not None:
                line += f", {round(accuracy * 100)}% accuracy on {attempts} attempts"
            if top_errors:
                line += f", recurring errors: {', '.join(str(e) for e in top_errors[:4])}"
            line += "]"
            parts.append(line)
        if errors:
            summaries = []
            for err in errors[:5]:
                if isinstance(err, dict):
                    cat = err.get("category", "")
                    tid = err.get("topic_id", "")
                    count = err.get("count", "")
                    summaries.append(f"{cat}/{tid} x{count}" if count else f"{cat}/{tid}")
                else:
                    summaries.append(str(err))
            if summaries:
                parts.append("[Recent mistakes to address: " + "; ".join(summaries) + "]")
        if history:
            for item in history[-4:]:
                if not isinstance(item, dict):
                    continue
                role = item.get("role", "student")
                text = str(item.get("text", ""))[:300]
                if text:
                    parts.append(f"[{role} said: {text}]")
        if student_answer:
            parts.append(f"[Student's submitted answer: {student_answer}]")
        parts.append(f"[Student's message: {message}]" if message else "")

        instruction = self._MODE_INSTRUCTIONS.get(mode, self._MODE_INSTRUCTIONS["explain"])
        system = (
            "You are an extremely demanding but highly effective EDHEC Business School "
            "Venture Capital professor preparing a student for a 90-minute English exam.\n\n"
            "STRICT RULES:\n"
            "- ALWAYS respond in English. No French.\n"
            "- Be precise on formulas, units, and financial conventions.\n"
            "- Never invent a source, a formula, or a course reference. If the provided "
            "course context does not cover the point, say explicitly: "
            '"Not covered in the provided course extracts — verify before the exam."\n'
            "- Keep it focused: this is a tutoring turn, not an essay.\n\n"
            f"YOUR TASK THIS TURN:\n{instruction}"
        )
        prompt = "\n".join(p for p in parts if p)
        context = self.get_relevant_context(
            " ".join(p for p in (message, topic_id or "", student_answer or "") if p),
            max_chars=6000,
        )
        if context:
            prompt = f"Course context:\n{context}\n\n{prompt}"

        result_text = None
        model_used = None
        for provider in ("gemini", "ollama"):
            if provider == "gemini":
                result_text = self.call_gemini(prompt, system)
                if result_text:
                    model_used = self._last_model or self._gemini_model()
            elif provider == "ollama":
                result_text = self.call_ollama(prompt, system)
                if result_text:
                    model_used = self.config.get("ollama_model", "qwen3.5:4b")
            if result_text:
                break

        passages = []
        if context:
            # Chunks themselves contain blank lines, so scan for citation
            # headers instead of splitting the whole context on blank lines.
            for line in context.splitlines():
                stripped = line.strip()
                if stripped.startswith("===") and "===" in stripped[3:]:
                    citation = stripped.strip("= ").strip()
                    if citation and citation not in {p["citation"] for p in passages}:
                        passages.append({"citation": citation})
                if len(passages) >= 5:
                    break

        if not result_text:
            return {
                "text": (
                    "No model available. Cloud is disabled or unreachable and local "
                    "Ollama is not running. Start Ollama, or enable the Gemini key, "
                    "to use the tutor. Flashcards, drills and exams keep working offline."
                ),
                "source": "offline",
                "mode": mode,
                "passages": passages,
                "model": None,
                "error": getattr(self, "last_error", None),
            }
        return {
            "text": self._redact(result_text),
            "source": "ai",
            "mode": mode,
            "passages": passages,
            "model": model_used,
        }
