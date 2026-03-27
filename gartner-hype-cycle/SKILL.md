---
name: gartner-hype-cycle
description: >
  Use when assessing technology maturity, judging adoption timing, or positioning a
  technology or market along the hype-to-productivity curve. Triggers on "hype cycle",
  "technology maturity", "Gartner", "adoption timing", "is this technology mature",
  "peak of inflated expectations", "trough of disillusionment", "技术成熟度曲线",
  "技术处于哪个阶段", "判断技术成熟度", "炒作周期", "新兴技术评估".
---

# Gartner Hype Cycle

Assess where a technology, innovation, or market sits on the maturity curve from initial
trigger to mainstream adoption. Created by Jackie Fenn (Gartner, 1995) and detailed in
*Mastering the Hype Cycle* (Fenn & Raskino, Harvard Business Press, 2008).

## Purpose

- Judge the maturity stage of a technology or industry trend
- Make informed adoption timing decisions (early mover vs. fast follower vs. wait)
- Separate genuine capability from hype-driven inflated expectations
- Align investment and resource allocation with realistic timelines

## When to Use

- Evaluating whether to invest in or adopt an emerging technology
- Building a technology strategy or innovation roadmap
- Advising stakeholders on realistic timelines for technology payoff
- Comparing maturity levels across competing technologies
- Assessing vendor claims against actual market maturity

## When NOT to Use

- For analyzing industry competitive structure (use Five Forces or SCP)
- For internal firm activity analysis (use Value Chain)
- For macro-environmental scanning (use PESTEL)
- When the technology is already commodity / fully mature (no hype to analyze)

## The Five Phases

```
Expectations
     ▲
     │        ②
     │       ╱╲  Peak of Inflated
     │      ╱  ╲ Expectations
     │     ╱    ╲
     │    ╱      ╲
     │   ╱        ╲          ⑤ Plateau of
     │  ╱          ╲        ╱  Productivity
     │ ╱            ╲   ④ ╱
     │╱              ╲  ╱ Slope of
     ①                ╲╱  Enlightenment
     │ Technology    ③
     │ Trigger       Trough of
     │               Disillusionment
     └──────────────────────────────────▶ Time
```

### Phase Details

| # | Phase | Characteristics | Signals |
|---|-------|-----------------|---------|
| 1 | **Technology Trigger** | A breakthrough, demo, or event generates early interest. No usable products yet. Viability unproven. | Lab demos, research papers, first VC funding, media curiosity articles |
| 2 | **Peak of Inflated Expectations** | Intense media hype, unrealistic claims. Some early success stories but many failures. Most organizations take no action. | Magazine covers, "will change everything" headlines, many startups, inflated valuations |
| 3 | **Trough of Disillusionment** | Interest wanes as experiments fail. Providers consolidate or fail. Investment continues only by persistent players. | Negative press, startup failures, customer disappointment, budget cuts |
| 4 | **Slope of Enlightenment** | Real-world benefits become understood. 2nd/3rd-gen products emerge. More enterprises pilot, though conservative firms remain cautious. | Best practice guides, ROI case studies, enterprise pilot programs, methodologies mature |
| 5 | **Plateau of Productivity** | Mainstream adoption begins. Market applicability and viability proven. Market penetration typically 20-30%+. | Standard procurement criteria, certified talent pool, stable vendor ecosystem |

### Time-to-Plateau Estimates

Gartner typically assigns each technology a "years to mainstream adoption" estimate:

| Label | Meaning |
|-------|---------|
| Less than 2 years | Rapid adoption expected |
| 2 to 5 years | Near-term mainstream |
| 5 to 10 years | Medium-term outlook |
| More than 10 years | Long-term or niche |
| Obsolete before plateau | May never reach mainstream |

## Application Process

### Step 1: Define the Technology/Trend

```markdown
- **Technology/Trend:** [e.g., "Generative AI for enterprise code generation"]
- **Scope:** [Global / specific market / specific use case]
- **Date of Assessment:** [Date]
- **Purpose:** [e.g., "Decide whether to invest in internal tooling now or wait"]
```

### Step 2: Gather Evidence for Phase Placement

For each phase, check whether its signals match:

| Evidence Category | Data Sources |
|-------------------|--------------|
| Media sentiment | News volume, tone (hype vs. skepticism), magazine covers |
| Investment activity | VC funding rounds, M&A, corporate R&D spend |
| Product maturity | Gen 1 vs. Gen 2+ products, feature completeness, stability |
| Adoption data | Enterprise pilots, production deployments, market penetration % |
| Vendor ecosystem | Number of vendors, consolidation, partnerships, certifications |
| Failure signals | Failed pilots, negative case studies, abandoned projects |

### Step 3: Place on the Curve

Based on the evidence, determine:
1. **Current phase** — which phase best matches the signal pattern?
2. **Direction** — ascending toward peak, descending toward trough, or climbing slope?
3. **Estimated time-to-plateau** — based on comparable technology trajectories

### Step 4: Assess Strategic Implications

Different phases demand different strategies:

| Phase | Recommended Strategy |
|-------|---------------------|
| Technology Trigger | **Monitor.** Track developments, assign scouts, no major investment |
| Peak of Inflated Expectations | **Experiment cautiously.** Small pilots, manage executive expectations, avoid bet-the-company decisions |
| Trough of Disillusionment | **Evaluate seriously.** Survivors have real capability; negotiate favorable terms with desperate vendors |
| Slope of Enlightenment | **Invest strategically.** Build internal capability, pilot at scale, develop best practices |
| Plateau of Productivity | **Optimize.** Focus on operational excellence, cost reduction, standard procurement |

### Step 5: Synthesize

```markdown
## Hype Cycle Assessment

### Technology: [Name]
### Current Phase: [Phase name]
### Evidence Summary:
- Media: [Hype level and sentiment]
- Investment: [Funding patterns]
- Products: [Maturity level]
- Adoption: [Deployment status]

### Time-to-Plateau Estimate: [X years]

### Strategic Recommendation:
[Action aligned with current phase — monitor / experiment / evaluate / invest / optimize]

### Key Risks:
1. [Risk if technology stalls in trough]
2. [Risk if competitors move faster]
3. [Risk of premature over-investment]
```

## Common Pitfalls

| Pitfall | Fix |
|---------|-----|
| Confusing media hype with actual adoption | Separate media volume from deployment data; count production users, not press releases |
| Assuming linear progression through phases | Technologies can stall, skip, or regress; some never reach the plateau |
| Treating the curve as predictive with precision | It is a mental model for strategic discussion, not a quantitative forecast |
| Ignoring that different use cases are in different phases | The same technology can be at Plateau for one use case and Trigger for another |
| Making the assessment once and never revisiting | Re-evaluate quarterly for fast-moving technologies |

## Limitations of the Framework

- **Not empirically validated as a predictive model** — the curve shape is conceptual
- **Gartner's own placements are subjective** — based on analyst judgment, not a formula
- **Survivorship bias** — the model focuses on technologies that eventually succeed
- **Single-dimension** — does not capture market size, competitive dynamics, or regulatory impact

Use the Hype Cycle as a **communication and discussion tool**, not as a decision-making algorithm.

## References

### Original Works

- Fenn, J. (1995). "When to Leap on the Hype Cycle." Gartner Research Note.
- Fenn, J. & Raskino, M. (2008). *Mastering the Hype Cycle: How to Choose the Right
  Innovation at the Right Time*. Harvard Business Press.
  - Amazon: https://www.amazon.com/Mastering-Hype-Cycle-Innovation-Gartner/dp/1422121100

### Authoritative References

- Gartner Official — Hype Cycle Methodology: https://www.gartner.com/en/research/methodologies/gartner-hype-cycle
- Wikipedia — Gartner hype cycle: https://en.wikipedia.org/wiki/Gartner_hype_cycle

### Related Frameworks

- **Technology Adoption Lifecycle** (Rogers, 1962) — Complementary model focusing on adopter categories (innovators → laggards)
- **Porter's Five Forces** — Assess industry-level competition once technology matures
- **PESTEL** — Macro factors (regulation, economics) that accelerate or delay adoption
