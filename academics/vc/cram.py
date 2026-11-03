"""One-page cram sheet, battle plan and printable HTML for the VC exam."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Iterable

from .pastpapers import PastPaper


@dataclass(frozen=True)
class Formula:
    name: str
    formula: str
    note: str


@dataclass(frozen=True)
class FormulaGroup:
    id: str
    title: str
    topic_id: str
    items: tuple[Formula, ...]


FORMULA_GROUPS: tuple[FormulaGroup, ...] = (
    FormulaGroup(
        "valuation",
        "1. Valuation and ownership",
        "VC04",
        (
            Formula(
                "Post-money",
                "V_POST = I / F_INV",
                "The investment I buys the fraction F_INV of the post-money company.",
            ),
            Formula(
                "Pre-money",
                "V_PRE = V_POST - I",
                "The investment changes the post-money value, never the negotiated pre-money value.",
            ),
            Formula(
                "Share price",
                "P = V_PRE / S_PRE",
                "S_PRE is the number of shares before the round (fully diluted if the pool is pre-money).",
            ),
            Formula(
                "New shares",
                "S_INV = I / P",
                "The investor receives shares at the negotiated price.",
            ),
            Formula(
                "Investor fraction",
                "F_INV = S_INV / (S_PRE + S_INV) = I / V_POST",
                "Equivalent formulations; use the one that matches the data given.",
            ),
            Formula(
                "Founder dilution",
                "F_FOUNDER,post = F_FOUNDER,pre x (1 - F_INV)",
                "Multiply by (1 - F_new) for every later round.",
            ),
        ),
    ),
    FormulaGroup(
        "cap-table",
        "2. Cap table and option pool",
        "VC05",
        (
            Formula(
                "Post-money shares with a pool",
                "S_TOTAL = S_FOUNDERS / (1 - F_INV - F_POOL)",
                "The pool is usually created before the investment, so it dilutes the founders, not the new investor.",
            ),
            Formula(
                "Pool shares",
                "S_POOL = F_POOL x S_TOTAL",
                "Use the post-money pool percentage stated in the term sheet.",
            ),
            Formula(
                "Investor shares",
                "S_INV = F_INV x S_TOTAL",
                "Check: founders + pool + investor = total.",
            ),
            Formula(
                "Fully diluted",
                "S_FD = common + options + warrants + convertibles",
                "Every security that can become common stock is counted.",
            ),
        ),
    ),
    FormulaGroup(
        "vc-method",
        "3. VC method and multi-round ownership",
        "VC09",
        (
            Formula(
                "Capital cash multiple",
                "CCM = (1 + h)^t",
                "h is the hurdle rate, t the years to exit.",
            ),
            Formula(
                "Post-money from exit",
                "V_POST = V_EXIT / CCM",
                "Discount the expected exit value back at the hurdle rate.",
            ),
            Formula(
                "Required ownership",
                "F_INV = I / V_POST = I x (1 + h)^t / V_EXIT",
                "This is the core VC-method formula.",
            ),
            Formula(
                "Exit ownership",
                "F_exit = F_post x (1 - F_next) x (1 - F_next2) ...",
                "A round is diluted by every subsequent round, not by earlier ones.",
            ),
            Formula(
                "Target-multiple ladder",
                "V_POST,last = V_EXIT / m_last; V_PRE,i = V_POST,i - I_i; V_POST,i-1 = V_PRE,i / m_i-1",
                "Work backwards from the exit when the case gives a target multiple per round.",
            ),
            Formula(
                "Exit proceeds",
                "Proceeds = F_exit x V_EXIT",
                "The multiple achieved is proceeds divided by the investment in that round.",
            ),
        ),
    ),
    FormulaGroup(
        "terms",
        "4. Term sheet economics and control",
        "VC06",
        (
            Formula(
                "Non-participating preference",
                "Payoff = max(LP, F x V_EXIT)",
                "The investor converts when conversion is worth more than the preference.",
            ),
            Formula(
                "Conversion threshold",
                "V* = LP / F",
                "Above V*, a non-participating investor converts.",
            ),
            Formula(
                "Participating preference",
                "Payoff = LP + F x (V_EXIT - LP), capped",
                "The cap is usually a multiple of LP; compare with conversion and take the maximum.",
            ),
            Formula(
                "Participating cap threshold",
                "V** = cap / F",
                "Above V**, even a participating investor prefers to convert.",
            ),
            Formula(
                "Broad-based weighted average",
                "CP2 = CP1 x (A + B) / (A + C)",
                "A = shares before the round, B = new money / CP1, C = new shares actually issued.",
            ),
            Formula(
                "Full ratchet",
                "CP2 = new issue price",
                "The harshest anti-dilution: the conversion price drops to the new round price.",
            ),
            Formula(
                "Reverse vesting",
                "Vested = shares x min(1, months / total months), after the cliff",
                "A 4-year monthly vesting with a 1-year cliff vests 25% at month 12.",
            ),
        ),
    ),
    FormulaGroup(
        "notes",
        "5. Convertible notes and SAFEs",
        "VC16",
        (
            Formula(
                "Discount price",
                "P_discount = P_new x (1 - discount)",
                "A 20% discount means the note pays 80% of the round price.",
            ),
            Formula(
                "Cap price",
                "P_cap = cap / fully diluted pre-money shares",
                "The cap is a maximum valuation, not a maximum price.",
            ),
            Formula(
                "Conversion price",
                "P_convert = min(P_discount, P_cap)",
                "The investor gets the better of the two protections.",
            ),
            Formula(
                "Shares issued",
                "S_note = amount / P_convert",
                "Interest and maturity add to the amount if the note is not converted earlier.",
            ),
        ),
    ),
    FormulaGroup(
        "lbo",
        "6. LBO, returns and attribution",
        "VC13",
        (
            Formula(
                "Entry / exit EV",
                "EV = multiple x EBITDA",
                "Use LTM EBITDA at entry and exit-year EBITDA at exit.",
            ),
            Formula(
                "Equity value",
                "Equity = EV - net debt",
                "Net debt = debt - cash.",
            ),
            Formula(
                "CFADS",
                "CFADS = EBITDA - capex - change in NWC - taxes",
                "Cash flow available for debt service.",
            ),
            Formula(
                "Free cash flow",
                "FCF = CFADS - interest",
                "With a cash sweep, debt falls by FCF each year.",
            ),
            Formula(
                "Debt schedule",
                "Debt_t = Debt_(t-1) - FCF_t",
                "Interest is computed on the opening debt balance.",
            ),
            Formula(
                "Cash-on-cash multiple",
                "CCM = exit equity / entry equity",
                "Use the sponsor's share if management rolls over equity.",
            ),
            Formula(
                "IRR",
                "IRR = CCM^(1/t) - 1",
                "Do not divide CCM by t; take the t-th root.",
            ),
            Formula(
                "Return attribution",
                "EBITDA impact = ΔEBITDA x entry multiple; multiple impact = Δmultiple x exit EBITDA; net-debt impact = entry debt - exit debt",
                "The three effects sum to the equity return.",
            ),
        ),
    ),
    FormulaGroup(
        "fund",
        "7. Fund economics and performance",
        "VC02",
        (
            Formula(
                "Management fee",
                "Fee = committed capital x fee %",
                "Often 2% of commitments during the investment period.",
            ),
            Formula(
                "Carried interest",
                "Carry = 20% x profits above the hurdle",
                "The hurdle is usually 8%; the catch-up restores the 80/20 split.",
            ),
            Formula(
                "TVPI",
                "TVPI = (distributions + NAV) / paid-in capital",
                "Total value divided by capital called.",
            ),
            Formula(
                "DPI / RVPI",
                "DPI = distributions / paid-in; RVPI = NAV / paid-in",
                "DPI is cash returned; RVPI is unrealized value.",
            ),
            Formula(
                "J-curve",
                "Early negative returns, later positive",
                "Caused by fees, write-downs and the timing of exits.",
            ),
        ),
    ),
)

TRAPS: tuple[tuple[str, str, str], ...] = (
    (
        "Pre-money vs post-money",
        "V_POST = V_PRE + I",
        "The investment amount affects the post-money value; the pre-money is negotiated separately.",
    ),
    (
        "Option pool",
        "The pool is usually pre-money",
        "It dilutes founders and earlier holders, not the new investor.",
    ),
    (
        "Fully diluted",
        "Count options, warrants and convertibles",
        "A percentage of the cap table that ignores the pool is not fully diluted.",
    ),
    (
        "Liquidation preference",
        "It is a floor, not a guarantee",
        "If the exit is below the preference, the investor receives the available proceeds, not the full LP.",
    ),
    (
        "Conversion",
        "Take the maximum of preference and conversion",
        "A non-participating investor converts only when F x exit > LP.",
    ),
    (
        "Participating preferred",
        "Apply the cap before comparing with conversion",
        "The cap is a multiple of the preference, not of the investment.",
    ),
    (
        "Anti-dilution",
        "Broad-based weighted average is softer than full ratchet",
        "Full ratchet resets the price to the new issue price; weighted average blends.",
    ),
    (
        "Convertible note",
        "Use the lower of discount price and cap price",
        "The two protections are not added; the investor takes the better one.",
    ),
    (
        "IRR",
        "IRR = CCM^(1/t) - 1",
        "Dividing the multiple by the holding period is the most common exam error.",
    ),
    (
        "Multi-round ownership",
        "Dilute by every later round",
        "Do not apply later dilution to earlier rounds twice, and do not forget it either.",
    ),
    (
        "LBO debt",
        "Interest is on the opening balance",
        "With a cash sweep, the balance falls each year, so interest falls too.",
    ),
    (
        "Return attribution",
        "Use the entry multiple for EBITDA, the exit EBITDA for the multiple effect",
        "The three effects must sum to the equity return.",
    ),
    (
        "Enterprise value",
        "EV = equity + debt - cash",
        "Issuing equity to repay debt leaves EV unchanged.",
    ),
    (
        "Strategic vs financial buyer",
        "Synergies and horizon explain the premium",
        "A financial buyer cannot pay for synergies it does not have.",
    ),
)


def plan_blocks(minutes: int = 90) -> list[dict[str, object]]:
    """Return a realistic, bounded revision plan."""

    minutes = max(15, int(minutes))
    if minutes >= 80:
        raw = [
            (8, "Dump the formula sheet from memory", "Write the 12 core formulas on blank paper. Check against `vc formulas`."),
            (20, "2025 multiple choice, timed", "`vc paper show 2025 --section A` then answer without looking at the solutions."),
            (10, "Correct the MCQ", "`vc paper grade 2025 --answers answers.json`; write down every trap you missed."),
            (30, "2025 calculations Q16-Q19", "Redo Palooka, the cap table, Miller/BST and the four-round ladder from scratch."),
            (18, "One case skeleton", "Q20 or Q21: write the table structure, the formulas and the recommendation, not the full prose."),
            (4, "Final checklist", "Preferences, anti-dilution, IRR root, option pool, later-round dilution."),
        ]
    elif minutes >= 50:
        raw = [
            (6, "Formula dump", "Core formulas only."),
            (18, "2025 MCQ, timed", "15 questions, 18 minutes."),
            (8, "Correct the MCQ", "Focus on the traps you missed."),
            (20, "Two calculation questions", "Palooka + cap table, or the four-round ladder."),
            (8, "Case outline", "One case, table + recommendation."),
        ]
    else:
        raw = [
            (5, "Formula dump", "The 12 formulas that cover 80% of the paper."),
            (10, "Ten MCQ", "`vc paper show 2025 --section A`."),
            (5, "Correct", "Read every solution, even the correct ones."),
        ]
    total = sum(block[0] for block in raw)
    scale = minutes / total if total else 1
    blocks: list[dict[str, object]] = []
    cursor = 0
    for index, (duration, title, detail) in enumerate(raw):
        allocated = max(1, round(duration * scale))
        if index == len(raw) - 1:
            allocated = max(1, minutes - cursor)
        start = cursor
        cursor += allocated
        blocks.append(
            {
                "start_minute": start,
                "end_minute": min(cursor, minutes),
                "minutes": allocated,
                "title": title,
                "detail": detail,
            }
        )
    return blocks


def formula_payload() -> dict[str, object]:
    return {
        "groups": [
            {
                "id": group.id,
                "title": group.title,
                "topic_id": group.topic_id,
                "items": [
                    {"name": item.name, "formula": item.formula, "note": item.note}
                    for item in group.items
                ],
            }
            for group in FORMULA_GROUPS
        ],
        "traps": [
            {"wrong": wrong, "right": right, "why": why} for wrong, right, why in TRAPS
        ],
        "plan": plan_blocks(90),
    }


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(
    papers: Iterable[PastPaper], *, minutes: int = 90, include_papers: bool = True
) -> str:
    papers = tuple(papers)
    lines: list[str] = []
    lines.append("# VC Exam Cram — EDHEC")
    lines.append("")
    lines.append(
        "A single offline sheet: the formulas, the traps, the 90-minute plan and the "
        "real past papers with worked solutions."
    )
    lines.append("")
    lines.append("## 90-minute battle plan")
    lines.append("")
    lines.append("| Start | Block | What to do |")
    lines.append("| --- | --- | --- |")
    for block in plan_blocks(minutes):
        lines.append(
            f"| {block['start_minute']:>2} min | {_md_escape(str(block['title']))} "
            f"| {_md_escape(str(block['detail']))} |"
        )
    lines.append("")
    lines.append("## Formula sheet")
    lines.append("")
    for group in FORMULA_GROUPS:
        lines.append(f"### {group.title} ({group.topic_id})")
        lines.append("")
        for item in group.items:
            lines.append(f"- **{item.name}** — `{item.formula}` — {item.note}")
        lines.append("")
    lines.append("## The 14 traps that cost marks")
    lines.append("")
    for index, (wrong, right, why) in enumerate(TRAPS, start=1):
        lines.append(f"{index}. **{wrong}** → {right}. {why}")
    lines.append("")
    if include_papers:
        lines.append("## Past papers with worked solutions")
        lines.append("")
        for paper in papers:
            lines.append(f"### {paper.year} — {paper.title} ({paper.duration_minutes} min)")
            lines.append("")
            if paper.notice:
                lines.append(f"> {paper.notice}")
                lines.append("")
            for question in paper.questions:
                lines.append(
                    f"#### Q{question.number} ({question.points:g} pts, {question.topic_id})"
                )
                lines.append("")
                lines.append(question.prompt)
                lines.append("")
                for choice in question.choices:
                    lines.append(f"- **{choice.label}.** {choice.text}")
                if question.choices:
                    lines.append("")
                if question.parts:
                    for part in question.parts:
                        lines.append(f"**{part.id}.** {part.prompt}")
                        lines.append("")
                        if part.answer:
                            lines.append(f"*Answer:* {part.answer}")
                            lines.append("")
                        lines.append(f"*Solution:* {part.solution}")
                        lines.append("")
                if question.answer and not question.parts:
                    lines.append(f"*Answer:* {question.answer}")
                    lines.append("")
                if question.solution:
                    lines.append(f"*Solution:* {question.solution}")
                    lines.append("")
    lines.append("## Last-minute checklist")
    lines.append("")
    lines.append("- [ ] Pre-money vs post-money, and what the investment changes.")
    lines.append("- [ ] Option pool is pre-money; founders absorb it.")
    lines.append("- [ ] Liquidation preference vs conversion; participating cap.")
    lines.append("- [ ] Anti-dilution: broad-based weighted average vs full ratchet.")
    lines.append("- [ ] Convertible note: lower of discount price and cap price.")
    lines.append("- [ ] IRR: t-th root, not division by t.")
    lines.append("- [ ] Multi-round: dilute by every later round.")
    lines.append("- [ ] LBO: interest on opening debt, debt falls by FCF.")
    lines.append("- [ ] Return attribution sums to the equity return.")
    lines.append("- [ ] Write the formula, the numbers, the unit, then the sentence.")
    lines.append("")
    return "\n".join(lines)


def _html_escape(text: str) -> str:
    return html.escape(str(text), quote=True)


def _points(value: float) -> str:
    return f"{value:g} pt" + ("" if value == 1 else "s")


def render_html(
    papers: Iterable[PastPaper], *, minutes: int = 90, title: str = "VC Exam Cram"
) -> str:
    papers = tuple(papers)
    plan_rows = "".join(
        f"<tr><td class='num'>{block['start_minute']:>2}–{block['end_minute']} min</td>"
        f"<td><strong>{_html_escape(str(block['title']))}</strong></td>"
        f"<td>{_html_escape(str(block['detail']))}</td></tr>"
        for block in plan_blocks(minutes)
    )
    formula_sections = []
    for group in FORMULA_GROUPS:
        items = "".join(
            f"<li><span class='fname'>{_html_escape(item.name)}</span>"
            f"<code>{_html_escape(item.formula)}</code>"
            f"<span class='fnote'>{_html_escape(item.note)}</span></li>"
            for item in group.items
        )
        formula_sections.append(
            f"<section class='card'><h3>{_html_escape(group.title)} "
            f"<span class='topic'>{_html_escape(group.topic_id)}</span></h3>"
            f"<ul class='formulas'>{items}</ul></section>"
        )
    trap_items = "".join(
        f"<li><strong>{_html_escape(wrong)}</strong> → {_html_escape(right)}. "
        f"<span class='muted'>{_html_escape(why)}</span></li>"
        for wrong, right, why in TRAPS
    )
    paper_sections = []
    for paper in papers:
        questions = []
        for question in paper.questions:
            choices = ""
            if question.choices:
                choices = "<ol class='choices'>" + "".join(
                    f"<li><span class='letter'>{choice.label}</span> {_html_escape(choice.text)}</li>"
                    for choice in question.choices
                ) + "</ol>"
            parts_visible = ""
            parts_solutions = ""
            if question.parts:
                visible_blocks = []
                solution_blocks = []
                for part in question.parts:
                    visible_blocks.append(
                        f"<div class='part'><p class='part-prompt'>"
                        f"<strong>{_html_escape(part.id)}.</strong> "
                        f"{_html_escape(part.prompt)}</p></div>"
                    )
                    answer = (
                        f"<p class='answer'><strong>Answer:</strong> "
                        f"{_html_escape(part.answer)}</p>"
                        if part.answer
                        else ""
                    )
                    solution_blocks.append(
                        f"<div class='part'><p class='part-prompt'>"
                        f"<strong>{_html_escape(part.id)}.</strong> "
                        f"{_html_escape(part.prompt)}</p>{answer}"
                        f"<p class='solution'><strong>Worked solution:</strong> "
                        f"{_html_escape(part.solution)}</p></div>"
                    )
                parts_visible = "".join(visible_blocks)
                parts_solutions = "".join(solution_blocks)
            answer = (
                f"<p class='answer'><strong>Answer:</strong> {_html_escape(question.answer)}</p>"
                if question.answer and not question.parts
                else ""
            )
            solution = (
                f"<p class='solution'><strong>Worked solution:</strong> "
                f"{_html_escape(question.solution)}</p>"
                if question.solution
                else ""
            )
            reveal = ""
            if answer or solution or parts_solutions:
                reveal = (
                    f"<details class='reveal'><summary>Show solution</summary>"
                    f"{answer}{solution}{parts_solutions}</details>"
                )
            questions.append(
                f"<article class='question' id='{_html_escape(question.id)}'>"
                f"<header><span class='qnum'>Q{question.number}</span>"
                f"<span class='meta'>{_points(question.points)} · {_html_escape(question.topic_id)}</span></header>"
                f"<p class='prompt'>{_html_escape(question.prompt)}</p>{choices}"
                f"{parts_visible}{reveal}"
                f"</article>"
            )
        paper_sections.append(
            f"<section class='paper'><h2>{paper.year} — {_html_escape(paper.title)}</h2>"
            f"<p class='muted'>{_html_escape(paper.notice)} · {paper.duration_minutes} min · "
            f"{len(paper.questions)} questions</p>{''.join(questions)}</section>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html_escape(title)}</title>
<style>
:root {{ color-scheme: light; --ink:#14213d; --muted:#5b6475; --accent:#0b6e4f; --line:#dce3ea; --bg:#f6f7f9; --card:#fff; --warn:#fff4e5; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color:var(--ink); background:var(--bg); }}
main {{ max-width: 1040px; margin: 0 auto; padding: 28px 20px 80px; }}
h1 {{ font-size: 2rem; margin: 0 0 6px; letter-spacing:-.02em; }}
h2 {{ margin-top: 42px; border-bottom: 2px solid var(--ink); padding-bottom: 6px; }}
h3 {{ margin: 0 0 10px; font-size: 1.05rem; }}
.lede {{ color: var(--muted); margin: 0 0 24px; max-width: 70ch; }}
.card {{ background: var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin:12px 0; }}
.topic {{ font: 600 11px/1 ui-monospace, monospace; color:var(--accent); background:#e8f3ee; padding:3px 6px; border-radius:999px; vertical-align:middle; }}
.formulas {{ list-style:none; margin:0; padding:0; }}
.formulas li {{ padding:9px 0; border-top:1px dashed var(--line); }}
.formulas li:first-child {{ border-top:0; }}
.fname {{ display:block; font-weight:650; }}
code {{ display:inline-block; margin:3px 0; padding:2px 6px; background:#eef2f6; border-radius:5px; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }}
.fnote {{ display:block; color:var(--muted); font-size:.92rem; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
th,td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ background:#edf1f5; font-size:.88rem; text-transform:uppercase; letter-spacing:.04em; }}
tr:last-child td {{ border-bottom:0; }}
.num {{ white-space:nowrap; font: 600 13px/1.5 ui-monospace, monospace; color:var(--accent); }}
.traps {{ padding-left: 20px; }}
.traps li {{ margin: 8px 0; }}
.paper {{ margin-top: 32px; }}
.question {{ background: var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin:12px 0; }}
.question header {{ display:flex; justify-content:space-between; gap:12px; align-items:baseline; margin-bottom:8px; }}
.qnum {{ font-weight:750; font-size:1.05rem; }}
.meta {{ color:var(--muted); font-size:.82rem; font-family: ui-monospace, monospace; }}
.prompt {{ margin:0 0 10px; }}
.choices {{ list-style:none; padding:0; margin:10px 0; }}
.choices li {{ padding:5px 0; }}
.letter {{ display:inline-block; width:22px; height:22px; line-height:22px; text-align:center; border-radius:50%; background:#e8f3ee; color:var(--accent); font-weight:700; font-size:.8rem; margin-right:6px; }}
.part {{ border-left:3px solid #e8f3ee; padding-left:12px; margin:12px 0; }}
.part-prompt {{ margin:0 0 6px; }}
.answer {{ background:#e8f3ee; padding:8px 10px; border-radius:8px; }}
.solution {{ color:#243b53; }}
details.reveal {{ margin-top:10px; }}
details.reveal summary {{ cursor:pointer; color:var(--accent); font-weight:650; }}
details.reveal[open] summary {{ margin-bottom:8px; }}
.muted {{ color:var(--muted); }}
.checklist {{ columns: 2; column-gap: 32px; }}
.checklist li {{ break-inside: avoid; margin-bottom:8px; }}
@media (max-width: 720px) {{ .checklist {{ columns:1; }} h1 {{ font-size:1.6rem; }} }}
@media print {{
  body {{ background:#fff; font-size:11pt; }}
  main {{ max-width:none; padding:0; }}
  .card,.question,table {{ break-inside: avoid; }}
  details.reveal {{ display:block; }}
  details.reveal summary {{ display:none; }}
}}
</style>
</head>
<body>
<main>
<h1>{_html_escape(title)}</h1>
<p class="lede">Everything you need in one offline page: the formulas, the traps, the 90-minute plan and every past paper with a worked solution. Print it or keep it open while you revise.</p>
<h2>90-minute battle plan</h2>
<table><thead><tr><th>Time</th><th>Block</th><th>What to do</th></tr></thead><tbody>{plan_rows}</tbody></table>
<h2>Formula sheet</h2>
{''.join(formula_sections)}
<h2>The 14 traps that cost marks</h2>
<ol class="traps">{trap_items}</ol>
<h2>Past papers with worked solutions</h2>
{''.join(paper_sections)}
<h2>Last-minute checklist</h2>
<ul class="checklist">
<li>Pre-money vs post-money: the investment changes post-money only.</li>
<li>Option pool is pre-money; founders absorb it.</li>
<li>Liquidation preference vs conversion; participating cap.</li>
<li>Anti-dilution: weighted average vs full ratchet.</li>
<li>Convertible note: lower of discount price and cap price.</li>
<li>IRR: take the t-th root, never divide by t.</li>
<li>Multi-round: dilute by every later round.</li>
<li>LBO: interest on opening debt; debt falls by FCF.</li>
<li>Return attribution must sum to the equity return.</li>
<li>Write the formula, the numbers, the unit, then the sentence.</li>
</ul>
</main>
</body>
</html>
"""
