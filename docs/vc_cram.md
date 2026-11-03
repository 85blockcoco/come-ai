# VC Exam Cram — EDHEC

A single offline sheet: the formulas, the traps, the 90-minute plan and the real past papers with worked solutions.

## 90-minute battle plan

| Start | Block | What to do |
| --- | --- | --- |
|  0 min | Dump the formula sheet from memory | Write the 12 core formulas on blank paper. Check against `vc formulas`. |
|  8 min | 2025 multiple choice, timed | `vc paper show 2025 --section A` then answer without looking at the solutions. |
| 28 min | Correct the MCQ | `vc paper grade 2025 --answers answers.json`; write down every trap you missed. |
| 38 min | 2025 calculations Q16-Q19 | Redo Palooka, the cap table, Miller/BST and the four-round ladder from scratch. |
| 68 min | One case skeleton | Q20 or Q21: write the table structure, the formulas and the recommendation, not the full prose. |
| 86 min | Final checklist | Preferences, anti-dilution, IRR root, option pool, later-round dilution. |

## Formula sheet

### 1. Valuation and ownership (VC04)

- **Post-money** — `V_POST = I / F_INV` — The investment I buys the fraction F_INV of the post-money company.
- **Pre-money** — `V_PRE = V_POST - I` — The investment changes the post-money value, never the negotiated pre-money value.
- **Share price** — `P = V_PRE / S_PRE` — S_PRE is the number of shares before the round (fully diluted if the pool is pre-money).
- **New shares** — `S_INV = I / P` — The investor receives shares at the negotiated price.
- **Investor fraction** — `F_INV = S_INV / (S_PRE + S_INV) = I / V_POST` — Equivalent formulations; use the one that matches the data given.
- **Founder dilution** — `F_FOUNDER,post = F_FOUNDER,pre x (1 - F_INV)` — Multiply by (1 - F_new) for every later round.

### 2. Cap table and option pool (VC05)

- **Post-money shares with a pool** — `S_TOTAL = S_FOUNDERS / (1 - F_INV - F_POOL)` — The pool is usually created before the investment, so it dilutes the founders, not the new investor.
- **Pool shares** — `S_POOL = F_POOL x S_TOTAL` — Use the post-money pool percentage stated in the term sheet.
- **Investor shares** — `S_INV = F_INV x S_TOTAL` — Check: founders + pool + investor = total.
- **Fully diluted** — `S_FD = common + options + warrants + convertibles` — Every security that can become common stock is counted.

### 3. VC method and multi-round ownership (VC09)

- **Capital cash multiple** — `CCM = (1 + h)^t` — h is the hurdle rate, t the years to exit.
- **Post-money from exit** — `V_POST = V_EXIT / CCM` — Discount the expected exit value back at the hurdle rate.
- **Required ownership** — `F_INV = I / V_POST = I x (1 + h)^t / V_EXIT` — This is the core VC-method formula.
- **Exit ownership** — `F_exit = F_post x (1 - F_next) x (1 - F_next2) ...` — A round is diluted by every subsequent round, not by earlier ones.
- **Target-multiple ladder** — `V_POST,last = V_EXIT / m_last; V_PRE,i = V_POST,i - I_i; V_POST,i-1 = V_PRE,i / m_i-1` — Work backwards from the exit when the case gives a target multiple per round.
- **Exit proceeds** — `Proceeds = F_exit x V_EXIT` — The multiple achieved is proceeds divided by the investment in that round.

### 4. Term sheet economics and control (VC06)

- **Non-participating preference** — `Payoff = max(LP, F x V_EXIT)` — The investor converts when conversion is worth more than the preference.
- **Conversion threshold** — `V* = LP / F` — Above V*, a non-participating investor converts.
- **Participating preference** — `Payoff = LP + F x (V_EXIT - LP), capped` — The cap is usually a multiple of LP; compare with conversion and take the maximum.
- **Participating cap threshold** — `V** = cap / F` — Above V**, even a participating investor prefers to convert.
- **Broad-based weighted average** — `CP2 = CP1 x (A + B) / (A + C)` — A = shares before the round, B = new money / CP1, C = new shares actually issued.
- **Full ratchet** — `CP2 = new issue price` — The harshest anti-dilution: the conversion price drops to the new round price.
- **Reverse vesting** — `Vested = shares x min(1, months / total months), after the cliff` — A 4-year monthly vesting with a 1-year cliff vests 25% at month 12.

### 5. Convertible notes and SAFEs (VC16)

- **Discount price** — `P_discount = P_new x (1 - discount)` — A 20% discount means the note pays 80% of the round price.
- **Cap price** — `P_cap = cap / fully diluted pre-money shares` — The cap is a maximum valuation, not a maximum price.
- **Conversion price** — `P_convert = min(P_discount, P_cap)` — The investor gets the better of the two protections.
- **Shares issued** — `S_note = amount / P_convert` — Interest and maturity add to the amount if the note is not converted earlier.

### 6. LBO, returns and attribution (VC13)

- **Entry / exit EV** — `EV = multiple x EBITDA` — Use LTM EBITDA at entry and exit-year EBITDA at exit.
- **Equity value** — `Equity = EV - net debt` — Net debt = debt - cash.
- **CFADS** — `CFADS = EBITDA - capex - change in NWC - taxes` — Cash flow available for debt service.
- **Free cash flow** — `FCF = CFADS - interest` — With a cash sweep, debt falls by FCF each year.
- **Debt schedule** — `Debt_t = Debt_(t-1) - FCF_t` — Interest is computed on the opening debt balance.
- **Cash-on-cash multiple** — `CCM = exit equity / entry equity` — Use the sponsor's share if management rolls over equity.
- **IRR** — `IRR = CCM^(1/t) - 1` — Do not divide CCM by t; take the t-th root.
- **Return attribution** — `EBITDA impact = ΔEBITDA x entry multiple; multiple impact = Δmultiple x exit EBITDA; net-debt impact = entry debt - exit debt` — The three effects sum to the equity return.

### 7. Fund economics and performance (VC02)

- **Management fee** — `Fee = committed capital x fee %` — Often 2% of commitments during the investment period.
- **Carried interest** — `Carry = 20% x profits above the hurdle` — The hurdle is usually 8%; the catch-up restores the 80/20 split.
- **TVPI** — `TVPI = (distributions + NAV) / paid-in capital` — Total value divided by capital called.
- **DPI / RVPI** — `DPI = distributions / paid-in; RVPI = NAV / paid-in` — DPI is cash returned; RVPI is unrealized value.
- **J-curve** — `Early negative returns, later positive` — Caused by fees, write-downs and the timing of exits.

## The 14 traps that cost marks

1. **Pre-money vs post-money** → V_POST = V_PRE + I. The investment amount affects the post-money value; the pre-money is negotiated separately.
2. **Option pool** → The pool is usually pre-money. It dilutes founders and earlier holders, not the new investor.
3. **Fully diluted** → Count options, warrants and convertibles. A percentage of the cap table that ignores the pool is not fully diluted.
4. **Liquidation preference** → It is a floor, not a guarantee. If the exit is below the preference, the investor receives the available proceeds, not the full LP.
5. **Conversion** → Take the maximum of preference and conversion. A non-participating investor converts only when F x exit > LP.
6. **Participating preferred** → Apply the cap before comparing with conversion. The cap is a multiple of the preference, not of the investment.
7. **Anti-dilution** → Broad-based weighted average is softer than full ratchet. Full ratchet resets the price to the new issue price; weighted average blends.
8. **Convertible note** → Use the lower of discount price and cap price. The two protections are not added; the investor takes the better one.
9. **IRR** → IRR = CCM^(1/t) - 1. Dividing the multiple by the holding period is the most common exam error.
10. **Multi-round ownership** → Dilute by every later round. Do not apply later dilution to earlier rounds twice, and do not forget it either.
11. **LBO debt** → Interest is on the opening balance. With a cash sweep, the balance falls each year, so interest falls too.
12. **Return attribution** → Use the entry multiple for EBITDA, the exit EBITDA for the multiple effect. The three effects must sum to the equity return.
13. **Enterprise value** → EV = equity + debt - cash. Issuing equity to repay debt leaves EV unchanged.
14. **Strategic vs financial buyer** → Synergies and horizon explain the premium. A financial buyer cannot pay for synergies it does not have.

## Past papers with worked solutions

### 2023 — EDHEC Private Equity, VC & M&A — Final Exam 2023 (120 min)

> Derived study pack: questions are condensed and paraphrased from the 2023 EDHEC past paper; numerical answers and worked solutions are reproduced.

#### Q1 (1 pts, VC01)

Which statement about private equity is FALSE?

- **A.** There is a liquid secondary market for trading PE investments.
- **B.** PE is sometimes accused of short-term measures that boost exit value at the expense of long-term prospects.
- **C.** A company may use PE financing to repurchase shares and go private.
- **D.** An entrepreneur can use business-angel networks to source seed capital.

*Answer:* A

*Solution:* PE interests are illiquid and trade only on a limited secondary market, usually through fund stakes or structured secondaries.

#### Q2 (1 pts, VC01)

Which PE strategy sees the highest euro amount invested in Europe every year?

- **A.** Buyout.
- **B.** Growth equity.
- **C.** Venture capital.
- **D.** Rescue / turnaround.

*Answer:* A

*Solution:* Buyout is the largest PE segment by invested capital in Europe; VC is much smaller in euro terms.

#### Q3 (1 pts, VC03)

VC firms typically use staged financing in order to:

- **A.** Incentivize the entrepreneur to reach predefined milestones.
- **B.** Acquire information about the founder's true ability, reducing informational asymmetries.
- **C.** Keep the option to abandon low-return ventures and fund only good performers.
- **D.** All of the above.

*Answer:* D

*Solution:* All three motives are standard: incentives, information acquisition and the abandonment option.

#### Q4 (1 pts, VC04)

The amount invested in a venture deal:

- **A.** Affects pre-money valuation.
- **B.** Affects post-money valuation.
- **C.** Affects both pre- and post-money valuation.
- **D.** Does not affect valuation.

*Answer:* B

*Solution:* Post-money = pre-money + investment. The negotiated pre-money value is independent of the cheque size.

#### Q5 (1 pts, VC05)

A stock-options pool is 'fully diluted' when:

- **A.** Later rounds dilute the pool's ownership stake.
- **B.** All options are exercised and converted into common shares.
- **C.** Employees let options expire because they are worthless.
- **D.** Grants exceed the issued share capital.

*Answer:* B

*Solution:* Fully diluted treats all options and convertibles as exercised/converted.

#### Q6 (1 pts, VC13)

Which characteristics represent an attractive LBO candidate?

- **A.** Irregular cash flow and substantial assets.
- **B.** High capex requirements and a small asset base.
- **C.** Predictable cash flow and substantial assets.
- **D.** Substantial assets and insubstantial cash flow.

*Answer:* C

*Solution:* LBOs need stable cash flow to service debt and assets to collateralize it.

#### Q7 (1 pts, VC14)

All of the following are reasons why EBITDA matters in comparable-company analysis EXCEPT:

- **A.** It is a more accurate look at operating cash flow.
- **B.** It is free from capital-structure differences.
- **C.** It represents profit after all expenses have been netted out.
- **D.** It is free from tax differences.

*Answer:* C

*Solution:* EBITDA is before interest, taxes, depreciation and amortization; it is not profit after all expenses.

#### Q8 (1 pts, VC13)

What happens to enterprise value if a company issues equity and uses the proceeds to repay debt?

- **A.** EV goes up.
- **B.** EV remains the same.
- **C.** EV goes down.
- **D.** It depends.

*Answer:* B

*Solution:* Equity rises by the amount debt falls (cash is unchanged after the round-trip), so EV = equity + debt - cash is unchanged.

#### Q9 (1 pts, VC13)

In an LBO, which correctly ranks the capital structure from most senior to most junior?

- **A.** High-yield bonds, mezzanine, equity, bank debt.
- **B.** Equity, mezzanine, high-yield bonds, bank debt.
- **C.** Equity, high-yield bonds, mezzanine, bank debt.
- **D.** Bank debt, mezzanine, high-yield bonds, equity.

*Answer:* D

*Solution:* Bank debt is senior secured; mezzanine is subordinated; high-yield bonds are typically unsecured/junior; equity is last.

#### Q10 (1 pts, VC13)

Which generally provides the highest valuation on a football-field graphic?

- **A.** DCF.
- **B.** LBO.
- **C.** Company comparables.
- **D.** Transaction comparables.

*Answer:* D

*Solution:* Transaction comparables include a control premium and synergies, so they usually sit at the top of the football field.

#### Q11 (2 pts, VC14)

EBITDA is $200m, COGS $200m, sales $1,000m and net income $150m. What is the EBITDA margin?

- **A.** 20%.
- **B.** 15%.
- **C.** 40%.
- **D.** 25%.

*Answer:* A

*Solution:* EBITDA margin = 200 / 1,000 = 20%. COGS and net income are distractors.

#### Q12 (2 pts, VC13)

Offer price $20, fully diluted shares 100m, total debt $200m, cash $100m. What is the implied enterprise value ($m)?

- **A.** 2,000.
- **B.** 1,900.
- **C.** 2,100.
- **D.** 1,700.

*Answer:* C

*Solution:* Equity value = 20 × 100 = $2,000m. EV = equity + debt - cash = 2,000 + 200 - 100 = $2,100m.

#### Q13 (2 pts, VC13)

EBITDA $600m, capex $100m, interest $150m, increase in NWC $40m, D&A $200m, tax rate 40%. What is free cash flow ($m)?

- **A.** 310.
- **B.** 340.
- **C.** 210.
- **D.** 300.

*Answer:* C

*Solution:* EBIT = 600 - 200 = 400; EBT = 400 - 150 = 250; tax = 100. FCF = 600 - 100 - 40 - 150 - 100 = $210m.

#### Q14 (2 pts, VC13)

XO invested $10m five years ago in 5m convertible preferred shares (3 common each). Its common position is 30% of equity. IPO price $10, 8% underwriting fee. What exit proceeds can XO expect ($m)?

- **A.** 46.
- **B.** 50.
- **C.** 138.
- **D.** 150.

*Answer:* C

*Solution:* XO's 15m common shares are 30% of 50m total. Market cap = 50m × $10 = $500m; after the 8% fee = $460m; XO gets 30% = $138m.

#### Q15 (2 pts, VC09)

Using the XO data above, what is the IRR on the investment?

- **A.** 35.7%.
- **B.** 38.0%.
- **C.** 69.0%.
- **D.** 71.9%.

*Answer:* C

*Solution:* CCM = 138/10 = 13.8x over 5 years. IRR = 13.8^(1/5) - 1 = 69.0%.

#### Q16 (2 pts, VC02)

What are the steps of capital allocation in a distribution waterfall?

*Answer:* 1) Return contributed capital to LPs. 2) Pay the preferred return/hurdle (about 8%). 3) GP catch-up until the GP has 20% of profits. 4) Split the remainder 80/20 between LPs and GP. 5) Clawback if the GP was overpaid.

*Solution:* The standard European waterfall is deal-by-deal or fund-wide: capital, hurdle, catch-up, 80/20 carry, then a clawback/true-up at the end.

#### Q17 (2 pts, VC16)

In seed investing, what are convertible notes and when/why are they used?

*Answer:* Short-term debt-like instruments that convert into preferred shares at the next priced round, usually with a discount (10-20%) and/or a valuation cap. They avoid pricing an immature startup, are fast and cheap, and give the investor downside protection and control rights. Typical maturity is 12-24 months.

*Solution:* Key points: no valuation at issuance, conversion at a discount/cap, maturity and interest, speed and standardisation, and the tension between founder and investor incentives if the next round is delayed.

#### Q18 (2 pts, VC03)

Growth-equity funds target firms with high capex and working-capital needs. What are the three main types of target firms?

*Answer:* Mature SMEs; late-stage VC-backed firms/startups; corporate spin-offs/carve-outs.

*Solution:* Growth equity sits between VC and buyout: minority stakes, proven business models, capital for scaling rather than survival.

#### Q19 (2 pts, VC13)

Explain rollover equity. Is it a positive or a negative sign?

*Answer:* Equity that key pre-buyout shareholders (management, sometimes the seller) reinvest into the post-buyout company instead of cashing out. It is generally positive: it aligns management with the PE owner and signals the seller's continued belief; it also reduces the PE equity cheque. It can be negative if the seller wanted a full exit or if the fit with the PE is poor.

*Solution:* Mention alignment, signalling and financing benefits; also mention the seller's liquidity preference and potential conflicts.

#### Q20 (2 pts, VC13)

When would a sell-side M&A advisor recommend a broad auction?

*Answer:* When maximizing competition and price is the priority: a broad auction reaches many strategic and financial buyers, limits any single buyer's bargaining power and helps the board meet its fiduciary duty. Costs: heavy preparation, confidentiality risk, business disruption and 'taint' if the auction fails.

*Solution:* Contrast with a targeted process: a broad auction maximizes price but is noisy; a targeted process protects confidentiality and is better when the buyer set is narrow.

#### Q21 (15 pts, VC04)

Epäkunnossa Partners considers two startups. Both need €2m and would exit at €20m after two years if successful. Häviäjä: 10% success probability; Voittaja: 30%. Each founder has €3m expected lifetime income. The fund does not observe the founders' beliefs and assumes 20% success for both. It offers €2m at an €8m post-money with a 10% annual dividend and a 1.3x liquidation preference.

**2023-C16a.** What is each startup's expected exit value under the founder's belief? Is it worth investing (scrap value 0)?

*Answer:* Häviäjä: 10% × €20m = €2m (indifferent, not worth it after any hurdle). Voittaja: 30% × €20m = €6m (worth it).

*Solution:* Expected exit value = probability × exit value: €2m vs €6m. Against a €2m investment, Häviäjä barely breaks even; Voittaja has a positive expected payoff.

**2023-C16b.** What ownership fraction and preferred terms does the offer imply? What is the conversion threshold?

*Answer:* Ownership = 2/8 = 25%. Preferred value = 2×1.3 + 2×10%×2 = €3.0m. Conversion threshold = 3.0/0.25 = €12m.

*Solution:* Preferred terms: 1.3× liquidation preference (€2.6m) plus two years of 10% dividends (€0.4m) = €3.0m. The VC converts when 25% of exit exceeds €3m, i.e. above €12m.

**2023-C16c.** On success, what are the payoffs for the VC and the founders?

*Answer:* Exit €20m > €12m threshold, so the VC converts: VC = 25% × €20m = €5m; founders = €15m.

*Solution:* Because conversion beats the preference (€5m > €3m), the VC converts. Founders keep the residual €15m.

**2023-C16d.** Would each founder accept, given €3m lifetime income? Does the term sheet screen out the weaker startup?

*Answer:* Häviäjä: 10% × €15m = €1.5m < €3m → reject. Voittaja: 30% × €15m = €4.5m > €3m → accept. Yes, the contract screens out the low-quality startup.

*Solution:* The founder compares the expected payoff with the outside option (€3m). Only the high-type founder accepts, so the term sheet is a screening device.

#### Q22 (15 pts, VC13)

Æble PE Partners buys Eple Co. at 8x LTM EBITDA and exits after three years at the same 8x. 50% debt at 10% with a cash sweep. LTM revenue $100m, growing 20% for two years; EBITDA margin 40%, flat; capex and depreciation 20% of revenue; no change in NWC; no tax for three years.

**2023-C17a.** Compute revenue, EBITDA, entry EV and exit EV ($m).

*Answer:* Revenue 100 / 120 / 144 / 172.8; EBITDA 40 / 48 / 57.6 / 69.12; entry EV $320m; exit EV $552.96m.

*Solution:* Revenue grows 20%: 100, 120, 144, 172.8. EBITDA = 40% of revenue: 40, 48, 57.6, 69.12. EV = 8 × EBITDA: 320 entry, 552.96 exit.

**2023-C17b.** Compute free cash flow and debt for each year ($m).

*Answer:* CFADS 24.0 / 28.8 / 34.56; interest 16.0 / 15.2 / 13.84; FCF 8.0 / 13.6 / 20.72; debt 160 / 152 / 138.4 / 117.68.

*Solution:* CFADS = EBITDA - capex (20% of revenue), NWC change 0. Interest = 10% of opening debt. FCF = CFADS - interest. Debt falls by FCF each year (cash sweep).

**2023-C17c.** Compute the exit equity value, cash return, CCM and IRR. Would you invest?

*Answer:* Exit equity = 552.96 - 117.68 = $435.28m; entry equity = $160m; return = $275.28m; CCM = 2.72x; IRR = 39.6%; yes (above the ~20-25% LBO threshold).

*Solution:* Equity = EV - debt. CCM = 435.28/160 = 2.72x. IRR = 2.72^(1/3) - 1 = 39.6%. The deal clears the usual LBO hurdle.

**2023-C17d.** Decompose the return into EBITDA, multiple and net-debt effects.

*Answer:* EBITDA: (69.12-40)×8 = $232.96m (84.6%); multiple: 0 (same 8x); net debt: 160-117.68 = $42.32m (15.4%).

*Solution:* EBITDA impact = ΔEBITDA × entry multiple. Multiple impact = (exit multiple - entry multiple) × exit EBITDA = 0. Net-debt impact = entry debt - exit debt. The three sum to the $275.28m return.

### 2024 — EDHEC Private Equity, VC & M&A — Final Exam 2024 (120 min)

> Derived study pack: questions are condensed and paraphrased from the 2024 EDHEC past paper; numerical answers and worked solutions are reproduced.

#### Q1 (1 pts, VC10)

What does 'first closing' mean in private-equity fundraising?

- **A.** The point at which the fund starts investing.
- **B.** The stage when the fund reaches its minimum required commitments to begin operations.
- **C.** The deadline for all LPs to make initial capital contributions.
- **D.** The stage when the manager finalizes total commitments.

*Answer:* B

*Solution:* First closing is when the fund has enough committed capital (the minimum size) to start investing; later closings add LPs.

#### Q2 (1 pts, VC02)

A 'catch-up' clause in private equity typically refers to:

- **A.** Allocating the first profits to LPs to meet the hurdle rate.
- **B.** Adjusting portfolio valuation to market conditions.
- **C.** Allocating profits disproportionately to GPs after LPs reach the hurdle rate.
- **D.** Reinvesting distributions into follow-on investments.

*Answer:* C

*Solution:* After the LP hurdle, the catch-up gives the GP a disproportionate share of subsequent profits until the 80/20 split is restored.

#### Q3 (1 pts, VC09)

Which best explains the J-curve in private equity?

- **A.** Performance dips early due to fees and initial losses, then rises as value is created.
- **B.** Portfolio companies grow exponentially through operational improvements.
- **C.** Initial distributions are delayed until all investments exit.
- **D.** GP compensation rises exponentially as the fund matures.

*Answer:* A

*Solution:* Early management fees and write-downs push returns below zero; later exits and value creation lift them.

#### Q4 (1 pts, VC14)

EBITDA is a proxy for:

- **A.** Sales.
- **B.** Operating cash flow.
- **C.** Growth.
- **D.** Debt.

*Answer:* B

*Solution:* EBITDA approximates operating cash flow before capex, working capital, interest and taxes.

#### Q5 (1 pts, VC03)

Which characteristic represents an attractive growth-equity candidate?

- **A.** Early-stage company with no product-market fit.
- **B.** Mature company with stagnant growth and limited scalability.
- **C.** Significant revenue growth, proven product-market fit and scaling potential.
- **D.** Company requiring heavy restructuring and capex.

*Answer:* C

*Solution:* Growth equity funds proven models into scaling, not turnarounds or unproven startups.

#### Q6 (1 pts, VC08)

What is the primary purpose of an anti-dilution clause?

- **A.** To prevent existing investor ownership from being diluted in future rounds.
- **B.** To restrict new shares issued to employees.
- **C.** To limit founders' ability to issue equity.
- **D.** To ensure debt is paid before equity.

*Answer:* A

*Solution:* It adjusts the preferred conversion price in a down round.

#### Q7 (1 pts, VC03)

What is the primary difference between seed-stage and Series A?

- **A.** Series A investors typically require board seats.
- **B.** Seed focuses on scaling; Series A on product-market fit.
- **C.** Seed builds and validates the product; Series A scales the business.
- **D.** Series A requires higher founder equity stakes.

*Answer:* C

*Solution:* Seed validates; Series A scales a repeatable model.

#### Q8 (1 pts, VC04)

In venture capital, pre-money valuation is:

- **A.** Always higher than post-money.
- **B.** Always lower than post-money.
- **C.** Lower than post-money if the venture progresses after investment.
- **D.** Lower than post-money if the entrepreneur negotiates well.

*Answer:* B

*Solution:* Post-money = pre-money + investment.

#### Q9 (1 pts, VC04)

The key inputs of the VC valuation model are:

- **A.** Investment, time-to-exit, exit value, hurdle rate.
- **B.** Investment, time-to-exit, exit value, risk-free rate, risk premium.
- **C.** Investment, number of rounds, exit value, hurdle rate.
- **D.** Investment, number of rounds, exit value, risk-free rate, risk premium.

*Answer:* A

*Solution:* The standard VC method uses I, t, exit value and hurdle.

#### Q10 (2 pts, VC04)

Palooka Products receives $5m today, exits at $50m in 5 years, VC hurdle 40%. What equity share does the VC require?

- **A.** 26%.
- **B.** 38%.
- **C.** 54%.
- **D.** 14%.

*Answer:* C

*Solution:* CCM = 1.4^5 = 5.378; post-money = 50/5.378 = 9.297; share = 5/9.297 = 53.8% ≈ 54%.

#### Q11 (1 pts, VC13)

Which financing structure most likely improves equity IRR in an LBO?

- **A.** Increasing subordinated debt.
- **B.** Reducing the equity contribution and increasing leverage.
- **C.** Interest-only senior debt in early years.
- **D.** Replacing floating-rate debt with fixed-rate debt.

*Answer:* B

*Solution:* More leverage means less equity for the same enterprise, so the equity return is magnified (if the deal performs).

#### Q12 (1 pts, VC13)

What is the primary purpose of a dividend recapitalization?

- **A.** Return capital to investors while retaining ownership.
- **B.** Reduce the company's debt burden.
- **C.** Raise new equity for growth.
- **D.** Refinance debt at a lower rate.

*Answer:* A

*Solution:* The portfolio company borrows to pay a dividend to the sponsor, returning cash without an exit.

#### Q13 (1 pts, VC13)

Which represents an attractive LBO candidate?

- **A.** Stable margins, low capex, declining industry.
- **B.** Strong cash flow, low leverage, cyclical demand.
- **C.** High margins, strong free cash flow, dominant position in a fragmented but stable industry.
- **D.** High growth, high retention, high working-capital needs and R&D.

*Answer:* C

*Solution:* Stable, cash-generative, defensible businesses support debt service.

#### Q14 (2 pts, VC13)

An LBO target is bought for $1,500m with $500m equity. After 5 years no debt is repaid and EV rises by $500m. What is the cash-on-cash multiple?

- **A.** 3x.
- **B.** 2x.
- **C.** 1x.
- **D.** 5x.

*Answer:* B

*Solution:* Entry debt = 1,000; exit EV = 2,000; exit equity = 1,000; 1,000/500 = 2x.

#### Q15 (2 pts, VC13)

CFO $125m, CFI $50m, mandatory debt repayment $30m, cash from balance sheet $20m. Cash available for optional debt repayment?

- **A.** $65m.
- **B.** $165m.
- **C.** $45m.
- **D.** $20m.

*Answer:* A

*Solution:* 125 - 50 - 30 + 20 = $65m.

#### Q16 (1 pts, VC13)

What is most critical when identifying buyers in a sell-side M&A transaction?

- **A.** Ability to secure financing.
- **B.** Alignment with the seller's strategic objectives and valuation expectations.
- **C.** Experience in previous M&A deals.
- **D.** Ability to retain management.

*Answer:* B

*Solution:* Strategic fit and price expectations determine whether a buyer is credible and likely to close.

#### Q17 (1 pts, VC13)

Which metric is most commonly used in merger-consequences analysis?

- **A.** EV/EBITDA.
- **B.** Return on equity.
- **C.** Earnings per share.
- **D.** Internal rate of return.

*Answer:* C

*Solution:* Merger consequences focus on EPS accretion/dilution for the acquirer.

#### Q18 (2 pts, VC04)

Discuss how financial-market conditions may affect the valuation of a new venture.

*Answer:* In the VC method, value depends on exit value, hurdle rate and time to exit. Interest rates raise hurdle rates and lower multiples; risk appetite lowers hurdles and raises multiples; liquidity affects both entry and exit; inflation affects projected revenue/EBITDA and multiples.

*Solution:* Structure: the three inputs; then rates, sentiment, liquidity and inflation, each with direction of effect.

#### Q19 (2 pts, VC07)

Do you agree that 'investor liquidation rights are fundamentally a way to force founders to do investors' will and should be resisted'?

*Answer:* No. Liquidation rights protect the investor's downside and enforce the need for an exit, which is necessary to return capital to LPs. They are tough but within fair practice; the real issue is calibration (preference size, participation, caps), not the existence of the right.

*Solution:* Take a clear position, explain the economic function (downside protection, exit discipline, LP liquidity) and qualify with the cost to founders.

#### Q20 (2 pts, VC03)

Discuss the trade-offs created by staged financing for the entrepreneur.

*Answer:* Advantages: progressively higher valuations, less dilution, strategic discipline. Disadvantages: funding risk if milestones are missed, short-termism, less freedom to pivot, dependence on market conditions at each round.

*Solution:* Give both sides and a conclusion: staging is efficient but shifts risk to the founder.

#### Q21 (2 pts, VC13)

What are four key credit statistics used to size LBO debt?

*Answer:* Total debt/EBITDA; senior debt/EBITDA; EBITDA interest coverage; fixed-charge coverage; debt-service coverage.

*Solution:* Any four of the five are accepted; explain that they cap leverage and protect lenders.

#### Q22 (2 pts, VC13)

Why have strategic buyers traditionally been able to outbid financial buyers in auctions?

*Answer:* Synergies (cost and revenue), a longer investment horizon, and cheaper/less constrained financing. Financial buyers need a 3-7 year exit and are limited by debt coverage.

*Solution:* Explain synergy value, horizon and cost of capital; note that financial buyers can still win when synergies are low or financing is cheap.

#### Q23 (10 pts, VC04)

Magical Genie: VW offers $2m at a $5m post-money; XY offers $1m at a $3m pre-money. Founder owns 3m shares. Sale at $10m after one year. Scenario 1 (75%): $1m more at $2/share. Scenario 2 (25%): $2m more at $0.25/share.

**2024-C23a.** Initial round: compute pre/post-money, price, investor shares, total shares and founder ownership.

*Answer:* VW: pre $3m, post $5m, price $1, 2m shares, 5m total, founder 60%. XY: pre $3m, post $4m, price $1, 1m shares, 4m total, founder 75%.

*Solution:* VW: 5-2=3 pre; 3/3=$1; 2/1=2m; 3/5=60%. XY: 3+1=4 post; 3/3=$1; 1/1=1m; 3/4=75%.

**2024-C23b.** Second round under both scenarios: new shares and founder ownership.

*Answer:* Scenario 1: VW 60%; XY 0.5m new, 4.5m total, founder 66.7%. Scenario 2: VW 4m new, 9m total, founder 33.3%; XY 8m new, 12m total, founder 25%.

*Solution:* Shares issued = amount / price. Scenario 1: 1/2=0.5m. Scenario 2: 1/0.25=4m and 2/0.25=8m.

**2024-C23c.** Compute expected founder wealth with 75% probability on Scenario 1 and recommend an offer.

*Answer:* VW: 53.33% × $10m = $5.333m. XY: 56.25% × $10m = $5.625m. Take XY.

*Solution:* VW: 0.75×60% + 0.25×33.3% = 53.33%. XY: 0.75×66.7% + 0.25×25% = 56.25%.

**2024-C23d.** If the angels used a complex VC term sheet instead of common equity, which part of the calculations would change?

*Answer:* The exit-value distribution, not the ownership maths: liquidation preferences, participation and anti-dilution change the split between founder and investor, so the founder's expected wealth falls.

*Solution:* Preferred terms reallocate exit proceeds; ownership fractions can stay the same while payoffs change.

#### Q24 (10 pts, VC13)

Alma PE buys Apfel at 8x LTM EBITDA and exits after 2 years at 8.5x. 60% term-loan debt at 10% with cash sweep; management rolls over 10% of equity, sponsor funds 90%. LTM revenue $100m, +10% p.a.; EBITDA margin 35%, then 38%, then 40%. NWC and capex 10% of revenue; depreciation 10% of revenue; 0% tax.

**2024-C24a.** Compute revenue, EBITDA, entry EV and exit EV ($m).

*Answer:* Revenue 100 / 110 / 121; EBITDA 35 / 41.8 / 48.4; entry EV $280m; exit EV $411.4m.

*Solution:* Revenue grows 10%. EBITDA = margin × revenue. EV = 8×35 = 280 entry; 8.5×48.4 = 411.4 exit.

**2024-C24b.** Compute CFADS, interest, FCF and debt for each year ($m).

*Answer:* CFADS 30.12 / 35.64; interest 16.80 / 15.47; FCF 13.32 / 20.17; debt 168 / 154.68 / 134.51.

*Solution:* The official solution table uses NWC = 10% of EBITDA, although the case wording says 10% of revenue: 10%×35 = 3.50; 10%×41.8 = 4.18 → ΔNWC = 0.68; 10%×48.4 = 4.84 → ΔNWC = 0.66. Capex is 10% of revenue: 11.00 and 12.10. CFADS = EBITDA - ΔNWC - capex. Interest = 10% of opening debt (16.80 then 15.47). FCF = CFADS - interest; debt falls by FCF.

**2024-C24c.** Compute entry/exit equity, sponsor equity cheque, return, CCM and IRR. Invest?

*Answer:* Entry equity $112m; sponsor cheque $100.8m; exit equity $276.89m; proceeds $249.20m; return $148.40m; CCM 2.47x; IRR 57.2%; yes.

*Solution:* Equity = EV - debt. Sponsor funds 90% of 112 = 100.8. Exit equity = 411.4 - 134.51 = 276.89. Management rolls over 10%, so the sponsor owns 90% of the exit equity: 90% × 276.89 = 249.20. Return = 249.20 - 100.80 = 148.40. CCM = 249.20/100.80 = 2.47x; IRR = 2.47^(1/2) - 1 = 57.2%. Yes, the deal clears the LBO hurdle.

**2024-C24d.** Decompose the return into EBITDA, multiple and net-debt effects.

*Answer:* Official solution: EBITDA impact $96.48m (65.0%), multiple impact $21.78m (14.7%), net-debt impact $30.14m (20.3%).

*Solution:* Use the case's decomposition: EBITDA impact = ΔEBITDA × entry multiple; multiple impact = Δmultiple × exit EBITDA; net-debt impact = entry debt - exit debt. The three sum to the $148.40m return.

### 2025 — EDHEC Venture Capital — Final Exam 2025 (90 min)

> Derived study pack: questions are condensed and paraphrased from the 2025 EDHEC VC past paper; numerical answers and worked solutions are reproduced.

#### Q1 (1 pts, VC03)

VC firms typically use staged financing in order to:

- **A.** Incentivize the entrepreneur to exert effort and reach predefined milestones.
- **B.** Acquire information about the founder's true ability, reducing asymmetric information.
- **C.** Keep the option to abandon ventures with low early returns.
- **D.** All of the above.

*Answer:* D

*Solution:* Staged financing does all three: it creates milestone incentives, reveals information about founder ability, and preserves the option to abandon weak ventures.

#### Q2 (1 pts, VC06)

Milestone-based contracting can create perverse incentives because:

- **A.** It lowers information asymmetry.
- **B.** It reduces agency costs.
- **C.** Entrepreneurs may distort effort to meet short-term measurable goals at the expense of long-term value.
- **D.** Investors lose board control.

*Answer:* C

*Solution:* The contract rewards observable short-term milestones; the founder may game them instead of maximizing long-term value.

#### Q3 (1 pts, VC03)

What is the primary difference between seed-stage and Series A funding rounds?

- **A.** Series A investors typically require board seats; seed investors do not.
- **B.** Seed-stage focuses on scaling operations; Series A focuses on product-market fit.
- **C.** Seed-stage builds and validates the product; Series A scales the business.
- **D.** Series A rounds require higher equity stakes from founders than seed rounds.

*Answer:* C

*Solution:* Seed money validates the product and early traction; Series A funds repeatable go-to-market and scaling.

#### Q4 (1 pts, VC01)

A cross-border VC chooses a common-law domicile primarily because:

- **A.** It lowers tax on carried interest.
- **B.** It standardizes IFRS accounting.
- **C.** Judicial precedent offers stronger enforcement of term-sheet rights and LP agreements.
- **D.** It allows multiple carry classes.

*Answer:* C

*Solution:* Common-law jurisdictions rely on precedent, which investors see as more predictable and enforceable for complex contracts.

#### Q5 (1 pts, VC05)

A stock-options pool is 'fully diluted' when:

- **A.** Subsequent funding rounds fully dilute the ownership stake attached to the pool.
- **B.** All options are exercised and converted into common shares.
- **C.** Employees do not exercise their options because these have become worthless.
- **D.** None of the above.

*Answer:* B

*Solution:* Fully diluted means every option, warrant and convertible security is treated as already converted into common shares.

#### Q6 (1 pts, VC04)

The key inputs of the venture-capital valuation model are:

- **A.** Investment, time-to-exit, exit value, hurdle rate.
- **B.** Investment, time-to-exit, exit value, risk-free rate, risk premium.
- **C.** Investment, number of rounds, exit value, hurdle rate.
- **D.** Investment, number of rounds, exit value, risk-free rate, risk premium.

*Answer:* A

*Solution:* The VC method discounts the expected exit value at the hurdle rate over the time to exit, then solves for the required ownership.

#### Q7 (1 pts, VC04)

In venture capital, pre-money valuation is:

- **A.** Always higher than post-money valuation.
- **B.** Always lower than post-money valuation.
- **C.** Lower than post-money valuation if the venture makes progress after investment.
- **D.** Lower than post-money valuation if the entrepreneur negotiates a good deal.

*Answer:* B

*Solution:* By definition, post-money = pre-money + investment, so pre-money is always lower (for a positive investment).

#### Q8 (1 pts, VC06)

Why might a VC prefer a lower valuation with stronger protective provisions to a higher valuation with weak protections?

- **A.** It increases the founder's control.
- **B.** It balances risk and expected return more effectively.
- **C.** It avoids dilution in future rounds.
- **D.** It reduces capital-gains taxation.

*Answer:* B

*Solution:* A lower price improves the VC's return, while protective terms limit downside; together they improve the risk-return trade-off.

#### Q9 (1 pts, VC04)

In the VC method, which of the following would NOT affect the investor's required ownership?

- **A.** Expected exit value.
- **B.** Time to exit.
- **C.** Hurdle rate.
- **D.** Liquidation preference.

*Answer:* D

*Solution:* Required ownership = I(1+h)^t / exit value. Liquidation preference changes the payoff split, not the ownership fraction.

#### Q10 (1 pts, VC08)

What is the primary purpose of an anti-dilution clause in a term sheet?

- **A.** To prevent existing investor ownership from being diluted in future funding rounds.
- **B.** To restrict the issuance of new shares to employees.
- **C.** To limit the founders' ability to issue new equity.
- **D.** To ensure debt obligations are paid before equity holders.

*Answer:* A

*Solution:* Anti-dilution adjusts the preferred conversion price in a down round, protecting the investor's effective ownership.

#### Q11 (1 pts, VC06)

Which clause aligns founder and investor incentives by allowing founders to 'earn back' shares through continued effort?

- **A.** Pay-to-play.
- **B.** Reverse vesting.
- **C.** Drag-along.
- **D.** Convertible note.

*Answer:* B

*Solution:* Reverse vesting means founders already own the shares, but unvested shares can be repurchased if they leave; continued service earns them back.

#### Q12 (1 pts, VC06)

In a term sheet, pay-to-play provisions are designed to:

- **A.** Force existing investors to participate in later rounds to retain preferential rights.
- **B.** Guarantee future investment opportunities to new investors.
- **C.** Protect founders from dilution in future rounds.
- **D.** Ensure anti-dilution adjustments always apply.

*Answer:* A

*Solution:* Pay-to-play converts non-participating preferred into common (or strips its preferences) if the investor does not fund its pro-rata share of a down round.

#### Q13 (1 pts, VC17)

When comparing U.S. and continental-European VC contracts, which is most accurate?

- **A.** European term sheets rely more on protective provisions.
- **B.** U.S. deals emphasize relationship-based monitoring.
- **C.** U.S. contracts are more legalistic; European deals rely more on trust and staged financing.
- **D.** No difference once English law governs both.

*Answer:* C

*Solution:* U.S. venture contracts are typically longer and more rule-based; continental European deals often rely more on relationship governance and staging.

#### Q14 (1 pts, VC06)

A founder is terminated 'for cause' one year after a 4-year reverse-vesting agreement with a 12-month cliff. They held 4 million founder shares. How many shares remain theirs?

- **A.** 1 million.
- **B.** 0.
- **C.** 3 million.
- **D.** 4 million.

*Answer:* A

*Solution:* The 12-month cliff vests 25% (1 million shares). The remaining 3 million are unvested and repurchased; the vested million stays with the founder.

#### Q15 (1 pts, VC16)

A VC invests in a convertible note with both a discount and a valuation cap. The dual benefits are:

- **A.** Only the cap applies in up rounds.
- **B.** Only the discount applies in down rounds.
- **C.** The VC captures upside if valuation soars and protection if it rises modestly.
- **D.** It prevents conversion to equity.

*Answer:* C

*Solution:* The investor converts at the lower of the discounted price and the cap price: the cap gives upside in a hot round, the discount gives a cushion in a moderate round.

#### Q16 (3 pts, VC04)

Palooka Products is negotiating a VC term sheet to receive $5 million today. It expects an IPO in 5 years at an exit value of $50 million. The VC requires a 40% hurdle rate. What share of equity will the VC accept? (answer in %).

*Answer:* 54

*Solution:* CCM = 1.40^5 = 5.378. Post-money value = 50 / 5.378 = $9.297m. Required ownership = 5 / 9.297 = 53.8% ≈ 54%.

#### Q17 (3 pts, VC05)

A startup has 5m founder shares. A VC invests $2m at an $8m post-money valuation and requires a 20% post-money option pool. Fill the cap table.

**2025-B17a.** How many shares are in the option pool (m)?

*Answer:* 1.8182

*Solution:* Investor fraction = 2/8 = 25%. Founders keep 100 - 25 - 20 = 55%. Total post-money shares = 5 / 0.55 = 9.0909m. Pool = 20% × 9.0909 = 1.8182m.

**2025-B17b.** How many shares does the VC receive (m)?

*Answer:* 2.2727

*Solution:* VC shares = 25% × 9.0909 = 2.2727m. Check: 5.0000 + 1.8182 + 2.2727 = 9.0909m.

**2025-B17c.** What percentage do the founders own after the round?

*Answer:* 55

*Solution:* Founders = 100% - 25% (VC) - 20% (pool) = 55%.

#### Q18 (4 pts, VC09)

Miller Venture Capital invested $5m in BST 8 years ago and received 1m convertible preferred shares (2 common shares each). After conversion BST has 15m shares; it will issue 3m new shares in the IPO.

**2025-B18a.** What fraction of BST's common shares will Miller own after the IPO? (in %)

*Answer:* 11

*Solution:* Miller owns 1m × 2 = 2m common shares. Post-IPO shares = 15m + 3m = 18m. Ownership = 2/18 = 11.1%.

**2025-B18b.** If the stock trades at $25 after the first day, what is Miller's IRR? (in %)

*Answer:* 33

*Solution:* Proceeds = 2m × $25 = $50m. CCM = 50/5 = 10x. IRR = 10^(1/8) - 1 = 33.35% ≈ 33%.

#### Q19 (5 pts, VC04)

A startup plans four rounds and expects a $6bn strategic acquisition in 7 years. Round data (investment, years to exit, target multiple): Seed $1m / 7y / 8x; Series A $25m / 6y / 5x; Series B $50m / 4y / 4x; Series C $200m / 2y / 3x. Compute the fully diluted ownership at exit.

**2025-B19a.** Seed post-money valuation ($m)?

*Answer:* 6.875

*Solution:* Work backwards along the target-multiple ladder. Series C post = exit / 3 = 6000/3 = 2000; C pre = 2000 - 200 = 1800. Series B post = 1800/4 = 450; B pre = 400. Series A post = 400/5 = 80; A pre = 55. Seed post = 55/8 = 6.875; Seed pre = 5.875. Seed ownership = 1/6.875 = 14.545%.

**2025-B19b.** Series A post-money valuation ($m)?

*Answer:* 80

*Solution:* Series A invests $25m for 31.25% post-money: 25 / 0.3125 = $80m.

**2025-B19c.** Series B post-money valuation ($m)?

*Answer:* 450

*Solution:* Series B invests $50m for 11.11%: 50 / 0.1111 = $450m.

**2025-B19d.** Series C post-money valuation ($m)?

*Answer:* 2000

*Solution:* Series C invests $200m for 10%: 200 / 0.10 = $2,000m.

**2025-B19e.** Founders' ownership at exit (in %)?

*Answer:* 47

*Solution:* Founders = 100% × (1 - 14.545%) × (1 - 31.25%) × (1 - 11.11%) × (1 - 10%) = 47.0%.

**2025-B19f.** Founders' exit proceeds ($m)?

*Answer:* 2820

*Solution:* 47.0% × $6,000m = $2,820m.

#### Q20 (15 pts, VC07)

Butchered Data (BD) raised $300k in convertible notes (20% discount, converts at the next round ≥ $2m). Two term sheets: Alpha invests $4m at a $9m post-money, 25% option pool, 1x non-participating liquidation preference, broad-based weighted-average anti-dilution, founders get 2 of 3 board seats. Mega invests $6m at a $12m post-money, 15% pool, 1x participating preference capped at 2.5x, full-ratchet anti-dilution, Mega gets 2 of 3 board seats, CEO shares 25% vested with 36-month monthly repurchase.

**2025-C20a.** Compare the two term sheets from the founders' perspective: valuation/ownership, anti-dilution, option pool, vesting, board control. Which do you recommend and why?

*Answer:* Mega on valuation/ownership and option pool; Alpha on anti-dilution, vesting and board control. Overall the founders should weigh Mega's higher founder ownership (31.9% vs 26.4%) against Alpha's much stronger governance and downside protection. A common answer is Mega if the founder is growth-confident, Alpha if control and down-round protection dominate.

*Solution:* Alpha: post $9m, price $1, 9m shares; VC 4m (44.4%), angel 0.375m (4.2%), pool 2.25m (25%), founders 26.4%. Mega: post $12m, price $1, 12m shares; VC 6m (50%), angel 0.375m (3.1%), pool 1.80m (15%), founders 31.9%. Mega gives more ownership and a smaller pool; Alpha gives broad-based weighted-average anti-dilution (softer than full ratchet), no forced vesting, and 2 founder board seats vs 1.

**2025-C20b.** Compute each investor's payoff at exit values of $5m, $10m, $28m and $35m.

*Answer:* Alpha (1x non-participating, 44.4%, LP $4m): $4m, $4.44m, $12.43m, $15.54m. Mega (1x participating, 50%, LP $6m, cap 2.5x = $15m): $5m, $8m, $15m, $17.5m.

*Solution:* Alpha: max(LP, 44.4% × exit) = max(4, 2.22)=4; max(4,4.44)=4.44; max(4,12.43)=12.43; max(4,15.54)=15.54. Mega: LP 6 then 50% of the remainder, capped at 15; if conversion is better, convert. Exit 5: min(5,6)=5. Exit 10: 6+0.5×4=8. Exit 28: 6+0.5×22=17 → cap 15. Exit 35: cap 15 vs conversion 17.5 → 17.5.

**2025-C20c.** If BD goes with Mega and a Series B is priced at $0.90, how many common shares will Mega's preferred convert to under full ratchet (m)?

*Answer:* 6.67

*Solution:* Full ratchet cuts the conversion price from $1.00 to $0.90. Mega's 6m preferred shares convert into 6 / 0.90 = 6.667m common shares.

#### Q21 (15 pts, VC04)

Magical Genie has two common-equity offers: VW invests $2m at a $5m post-money; XY invests $1m at a $3m pre-money. Founder Ali Baba owns 3m shares. After one year the company is sold for $10m, but it may need a second round: Scenario 1 needs $1m at $2/share (75% probability); Scenario 2 needs $2m at $0.25/share (25%).

**2025-C21a.** Initial round: compute pre-money, post-money, price per share, investor shares, total shares and founder ownership for each offer.

*Answer:* VW: pre $3m, post $5m, price $1, investor 2m shares, total 5m, founder 60%. XY: pre $3m, post $4m, price $1, investor 1m shares, total 4m, founder 75%.

*Solution:* VW: post = 5, pre = 5 - 2 = 3, price = 3/3 = $1, investor = 2/1 = 2m, total = 5m, founder = 3/5 = 60%. XY: post = 3 + 1 = 4, price = 3/3 = $1, investor = 1/1 = 1m, total = 4m, founder = 3/4 = 75%.

**2025-C21b.** Second round under each scenario: compute new shares and founder ownership.

*Answer:* Scenario 1: VW unchanged at 60%; XY issues 0.5m at $2, total 4.5m, founder 66.7%. Scenario 2: VW issues 4m at $0.25, total 9m, founder 33.3%; XY issues 8m at $0.25, total 12m, founder 25%.

*Solution:* Scenario 1: VW needs 0; XY raises 1/2 = 0.5m shares → 3/4.5 = 66.7%. Scenario 2: VW raises 1/0.25 = 4m → 3/9 = 33.3%; XY raises 2/0.25 = 8m → 3/12 = 25%.

**2025-C21c.** With Scenario 1 at 75% probability, compute each offer's expected founder wealth at a $10m exit and recommend one.

*Answer:* VW: 75% × 60% + 25% × 33.3% = 53.33% → $5.333m. XY: 75% × 66.7% + 25% × 25% = 56.25% → $5.625m. Take XY.

*Solution:* Expected ownership: VW = 0.75×0.60 + 0.25×0.3333 = 0.5333; XY = 0.75×0.6667 + 0.25×0.25 = 0.5625. Expected wealth = ownership × $10m: VW $5.333m, XY $5.625m. XY wins by $0.292m, but the difference is small and depends on the probability estimate.

## Last-minute checklist

- [ ] Pre-money vs post-money, and what the investment changes.
- [ ] Option pool is pre-money; founders absorb it.
- [ ] Liquidation preference vs conversion; participating cap.
- [ ] Anti-dilution: broad-based weighted average vs full ratchet.
- [ ] Convertible note: lower of discount price and cap price.
- [ ] IRR: t-th root, not division by t.
- [ ] Multi-round: dilute by every later round.
- [ ] LBO: interest on opening debt, debt falls by FCF.
- [ ] Return attribution sums to the equity return.
- [ ] Write the formula, the numbers, the unit, then the sentence.
