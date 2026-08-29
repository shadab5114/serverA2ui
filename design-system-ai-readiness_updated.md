# Design System AI Readiness — Playbook

A framework for measuring whether a design system's data is good enough for AI
agents, for improving it in a way that can be proven rather than asserted, and
for shipping it to the people who consume it.

**How to use this document.** Parts 1–4 are the measurement framework. Parts 5–7
are architecture and tooling. Part 8 is the execution plan — if you only act on
one section, act on that one. Parts 9–10 are traps and a checklist.

---

## Contents

1. [Premise](#1-premise)
2. [The readiness stack](#2-the-readiness-stack)
3. [Proving sufficiency](#3-proving-sufficiency)
4. [Failure attribution](#4-failure-attribution)
5. [Data architecture](#5-data-architecture)
6. [Layer 0 deep dive — data hygiene](#6-layer-0-deep-dive--data-hygiene)
7. [The tool surface](#7-the-tool-surface)
8. [Execution plan](#8-execution-plan)
9. [Traps](#9-traps)
10. [Checklist](#10-checklist)

---

## 1. Premise

**AI readiness is not a property of your assets. It is a measured success rate on
real tasks.**

A doc site does not have a readiness score any more than a hammer has one. The
question "do I have enough data?" cannot be answered by auditing the data. It can
only be answered by giving an agent realistic work, measuring what fraction it
gets right, and diagnosing what specifically broke.

That reframes the whole exercise as a loop:

```
define tasks → run agents → score → attribute each failure to a data gap
    → fix the data → re-run
```

Everything in this document is machinery for running that loop.

---

## 2. The readiness stack

Five layers. Lower layers are cheap and deterministic; upper layers are slow and
realistic. Run them all, weight attention by what fails.

```
Layer 0  Data hygiene      Coverage and correctness checks, CI on every change
Layer 1  Discovery         Can the agent find the right thing?
Layer 2  Selection         Did it pick the right component?
Layer 3  Generation        Does the code compile and comply?
Layer 4  End-to-end        Can it build a whole screen?
                                    ↓
         Failure attribution — every miss tagged to a cause
                                    ↻ becomes the data backlog
```

### Layer 0 — Data hygiene

Structural checks on the data itself. Necessary but not sufficient. Covered in
depth in [Part 6](#6-layer-0-deep-dive--data-hygiene).

### Layer 1 — Discovery

*Can the agent find the right thing?*

Build ~150 queries written the way a product engineer talks, not the way your
docs are titled. "dropdown", "picker", "select box", "let the user choose one of a
list" should all resolve to the same component. Record correct answers by hand.
Measure **recall@5**.

This is where design systems with distinctive internal naming fail silently. Docs
are indexed by internal names; users search by intent. The fix is synonym and
intent metadata in the catalog, not a better search engine.

### Layer 2 — Selection

*Did it pick the right component?*

Give an intent, not a name. "User needs to pick a date range for a bill cycle."
Compare the answer to what your best design system engineer would say. Score
exact match plus acceptable alternative.

Agents fail here more than anywhere. Not because they cannot write JSX, but
because nothing in the data answers *Modal vs Drawer vs inline panel* or *Toast vs
Banner vs inline error*. Per-component documentation structurally cannot answer a
cross-component question — whoever writes the Modal page writes it from Modal's
point of view.

### Layer 3 — Generation

*Does the produced code compile and comply?*

**For a design system, most of this scoring can be deterministic.** You have
TypeScript, a real component library, and a catalog. Use the compiler as the judge
instead of an LLM.

| Metric | How | Why it matters |
|---|---|---|
| Hallucination rate | Parse to AST; check every JSX element and prop against the catalog | The single most honest readiness signal |
| Typecheck pass | `tsc --noEmit` | Binary, no argument |
| Token adherence | Count raw hex / px / font stacks where a token exists | Does design intent survive? |
| Composition validity | Required providers present? Mutually exclusive props both set? | Catches structural misuse |
| Accessibility | Render in jsdom, run axe, count critical violations | Non-negotiable output quality |
| Visual diff | Compare against reference implementation | Expensive; add last |

### Layer 4 — End-to-end

Multi-turn, realistic tasks. Rubric-scored with human spot checks. Keep this set
small (10–15 tasks) — slow to run, but the only layer that catches
composition-scale problems.

---

## 3. Proving sufficiency

### The ablation method

This is how you move from "I think the data is good" to "I can show what each
asset is worth." Run the **same eval set** under different data configurations.

| Config | Setup |
|---|---|
| **A** | No design system context at all (plain React knowledge) |
| **B** | `llms.txt` only |
| **C** | Full docs in context |
| **D** | MCP tools enabled |
| **E** | MCP tools + validator |

The **deltas** are the evidence.

- If D beats B by two points, your MCP server is not earning its cost.
- If A already scores 60%, your bar is higher than you assumed and your headline
  number is flattering you.
- If E is the only config clearing your gate, validation is doing the work, not
  documentation.

### Setting baselines

There is no industry standard number to hit.

- **Floor:** Config A.
- **Ceiling:** A senior design-system-fluent engineer on the same tasks.
- **Goal:** Close X% of that gap.

Alongside the relative goal, set absolute CI gates. Starting placeholders, to be
replaced with your own observed distribution after two or three runs:

| Gate | Starting threshold |
|---|---|
| Hallucinated component or prop rate | < 1% |
| Typecheck pass | > 90% |
| Token adherence | > 95% |
| Critical a11y violations | 0 |
| Discovery recall@5 | > 90% |
| Selection match with expert | > 80% |

### The knowledge probe

A cheap, high-signal variant of Config A, borrowed from Meta's Astryx. Write five
questions a model will confidently get *wrong* without your docs — import paths,
a behaviour-to-prop mapping, a naming convention. Ship them in onboarding as a
self-check the agent runs before writing code.

Choose items with high discrimination: things where a pretrained model produces a
confident wrong answer rather than admitting ignorance. It doubles as an adoption
tool, because an adopter who watches their agent fail all five stops arguing about
whether setup is necessary.

---

## 4. Failure attribution

Every failed case gets exactly one tag. This is what converts eval scores into a
prioritised data backlog.

| Tag | Meaning | Owner |
|---|---|---|
| **A. Not findable** | The information exists, retrieval missed it | You |
| **B. Ambiguous** | Retrieval found several things, picked wrong | You |
| **C. Not specified** | Right doc found, doesn't answer the question | You |
| **D. Found and ignored** | Doc says it, buried in prose the agent skimmed | You |
| **E. Model limitation** | Nothing in your data would have helped | Not you |

Tag D matters more than expected. If a rule lives in paragraph nine of a page, it
effectively does not exist for an agent. That is a formatting fix, not a content
fix.

---

## 5. Data architecture

### 5.1 Derived vs authored

The single decision that determines whether hygiene is sustainable or a treadmill.

Anything typed by hand will drift. Not might — will. So classify every field, then
shrink the authored set as far as it will go.

| Derived — regenerate, never edit | Authored — write once, then test |
|---|---|
| Prop types, defaults, required flags | When to use / when not to use |
| Token names and values | Which alternative to use instead |
| Component and variant lists | Composition recipes |
| Runnable examples | Synonyms and intent phrasing |
| Version and deprecation state | Known anti-patterns |

**On the derived side, hygiene stops being a content problem and becomes a build
problem.** A hand-maintained props table has a decay rate. One generated from
TypeScript types has none.

**On the authored side is the uncomfortable part.** The fields that matter most to
an agent — which component to pick, what not to do, how things compose — are
exactly the ones that cannot be generated. Human effort previously spent on prop
tables should move there. Not more work; relocated work.

### 5.2 Always-loaded vs on-demand

A second axis, orthogonal to the first, and the one most teams miss.

| Always loaded (static context file) | On demand (MCP tools) |
|---|---|
| Rules that must always apply | Full props and API detail |
| The required workflow order | Examples and templates |
| Component name index | Token lookups |
| Import and setup conventions | Anything large or rare |
| *Cost: permanent token spend* | *Cost: the agent may not call it* |

**The selection criterion: if forgetting it silently breaks the output, it belongs
in always-loaded context.**

The failure this addresses is quiet but pervasive. *A tool that returns a
complete-looking answer suppresses further tool calls.* An agent asks about Button,
gets props, types, defaults and an example, and that looks finished. It has no
reason to suspect that "don't use Button for navigation" lives behind a different
tool it never called.

A sharper version of the criterion: go line by line and ask **what does TypeScript
catch here?** Missing CSS imports compile fine and render unstyled. Raw `<div>`
compiles fine. Hardcoded `#hex` compiles fine. Utility classes compile fine and do
nothing. Every one of those is a candidate for the always-loaded file, precisely
because nothing downstream will catch it.

### 5.3 Two audiences, one core

Designers and developers overlap far more than the framing suggests. "Should this
be a Drawer or a Modal?" is the identical question either way. So is "is there a
pattern for empty states?" **The decision content is audience-neutral. Only the
surface vocabulary differs.**

```
            ┌──────────────────────────────────────────────┐
            │           Shared intent layer                │
            │  purpose · when to use · alternatives ·      │
            │  composition · anti-patterns                 │
            └───────────────┬──────────────┬───────────────┘
                            │              │
              ┌─────────────▼───┐      ┌───▼─────────────┐
              │  Design facet   │◄────►│   Code facet    │
              │  Figma keys,    │ map  │  React exports, │
              │  variant props  │      │  props, types   │
              │  → designers    │      │  → developers   │
              └─────────────────┘      └─────────────────┘
```

**Do not build two stores.** Two sources of truth drift within a quarter, and —
more importantly — design-to-code *is* the join between them. If they're separate
systems, there is nothing to join.

### 5.4 The mapping manifest

The arrow in the middle is what almost nobody builds, and it's what makes
design-to-code work at all. Four levels of correspondence:

| Level | Figma side | Code side |
|---|---|---|
| Component | component key / node ID | React export name |
| Property | variant property `Size` | prop `size` |
| Value | `Large` | `"lg"` |
| Token | Figma variable ID | token name → CSS var |

Without this table, an agent handed a Figma frame is doing visual
pattern-matching: it sees a rounded rectangle with a label and guesses "Button."
With it, `1:2847` resolves deterministically.

### 5.5 Where everything lives

**The design metadata belongs in the code repo, not in Figma.**

Figma is an excellent authoring tool for visuals and a poor database. You cannot
branch it against a release, gate changes with a PR, or have CI validate it. A v5
mapping applied to a v6 library produces confidently wrong code, so the mapping
must version with the library.

| Layer | Where | Origin |
|---|---|---|
| Intent and decisions | repo, structured records | authored |
| Code facet | repo, from TSDoc | derived |
| Design facet | repo, synced from Figma API | derived |
| Mapping | repo, manifest | authored, then validated |
| Tokens | repo, StyleDictionary | derived |

One repo, one version number, one release. The docsite and the MCP server both
become *views* over this.

### 5.6 The reconciliation job

Once the design facet is in the repo, CI can pull the Figma library and diff
against the manifest:

- Components in Figma with no code counterpart
- Components in code with no Figma counterpart
- Variant properties whose names don't correspond
- Tokens that have diverged

This is the Layer 0 cross-surface check with teeth, and it's the only mechanism
that keeps designers and engineers from drifting apart without anyone noticing.

### 5.7 Guidelines as records, not pages

If guidelines are authored as markdown pages and the MCP server serves those
pages, then half your data is machine-shaped (typed records from TSDoc) and half
is human-shaped (paragraphs). The human-shaped half is exactly the high-value half
for agents.

**Invert the direction.** Author structured records; render the docsite page from
them.

```json
{
  "component": "Button",
  "rules": [
    {
      "id": "button-no-nav",
      "severity": "error",
      "condition": "the action navigates to a different route",
      "guidance": "do not use Button",
      "instead": "Link",
      "rationale": "breaks browser affordances: open in new tab, copy address"
    }
  ]
}
```

Four wins from one change: the tool returns rules instead of paragraphs; each rule
is atomically chunkable and self-contained; `instead` becomes a required field so
a "don't" can never ship without an alternative; and `condition` is
machine-checkable, so these records can later feed the validator.

---

## 6. Layer 0 deep dive — data hygiene

### 6.1 Completeness is not the thing being measured

The default approach is a checklist. The number goes up, everyone feels good, and
Layer 3 pass rates do not move. Presence and usefulness are different properties.

| Dimension | Question |
|---|---|
| **Presence** | Does it exist? |
| **Correctness** | Does it match what the code actually does? |
| **Consistency** | Do Figma, React, tokens, docs and catalog agree? |
| **Actionability** | Is it a rule an agent can apply, or prose a human interprets? |
| **Discoverability** | Does it use the words adopters use, or internal names? |
| **Freshness** | Has it drifted since the code changed? |

Most design systems score well on 1 and badly on 3, 4 and 5. Those three are where
agent failures actually come from.

### 6.2 Making authored content rule-shaped

> Consider using Drawer when you have a lot of content.

versus

> Use Drawer when content requires scrolling or exceeds the modal max height of
> 480px. Otherwise use Modal.

The first is prose a human interprets with judgement. The second is a condition an
agent evaluates. Both are "present". Only one is usable.

Two cheap tests:

1. **Hedge density.** Grep for *generally, typically, consider, it's recommended,
   may want to, in most cases*. High density is a reliable smell.
2. **Does every "when not to use" name a specific alternative?** Possibly the
   highest-value single check in the whole hygiene set. A prohibition with no exit
   leaves the agent nowhere to go, and it will invent something.

### 6.3 Chunk integrity

**The agent never reads your documentation page.**

A retrieval system slices every page into pieces of a few hundred tokens, embeds
each as a vector, and returns the closest three or four. The agent sees fragments
and nothing else. No page, no scroll, no heading above.

Mental image: someone tears the docs into index cards, shuffles them, and deals the
agent five. Every card must stand alone.

```
  Your doc page                       What the agent gets
  ─────────────────────────           ──────────────────────
  Button — when not to use
  Don't use Button for nav.
  ┄┄┄┄┄ chunk boundary ┄┄┄┄┄   ──►    <Button href="/plans">
  <Button href="/plans">                View plans
    View plans                        </Button>
  </Button>
                                      (the warning stayed behind)
```

#### Failure modes

| Mode | What happens |
|---|---|
| **Orphaned negation** | "Don't do this" heading in chunk A, the code in chunk B. The agent gets clean anti-pattern code from an authoritative source with nothing warning against it. Most dangerous — the docs actively teach the wrong thing. |
| **Heading orphaning** | Component name appears once in the H1. Every chunk below is about "the `size` prop" with no indication whose. Most widespread. |
| **Split rules** | Condition in one chunk, consequence in the next. Half a rule is worse than none. |
| **Lost antecedents** | "It must be wrapped in a provider." In a fragment, "it" refers to nothing. |
| **Decapitated tables** | Props table split mid-body loses its header row. |
| **Examples without imports** | Snippet in one chunk, imports in another. A common source of hallucinated import paths. |
| **Inherited context stated once** | "All form components require `FormProvider`" at the top of a family page. Forty component chunks below carry none of it. |

#### Why it hits twice

Chunks are embedded as vectors. A chunk that does not contain the word "Button"
matches weakly against a query about Button. Heading orphaning therefore degrades
**Layer 1 recall** as well as **Layer 3 correctness**. Fixing it moves both.

And unlike a human who lands mid-page and scrolls up, an agent cannot scroll up and
will not ask. It fills the gap with plausible invention — which, in a design system
context, is indistinguishable from correct code until it hits the build.

#### Fixes

- **Repeat instead of referencing.** The mindset flip. Human docs optimise for DRY.
  Agent docs optimise for chunk independence. If forty components need
  `FormProvider`, that line belongs on all forty pages. Redundancy that feels
  sloppy to a technical writer is what lets each fragment survive alone.
- **Chunk deliberately, not by character count.** Because docs are generated from
  the catalog, you control where cuts land. Emit boundaries at semantic units —
  one rule, one example, one section. Most teams do not have this option.
- **Prefix every chunk with breadcrumbs** before embedding:
  `Component: Button | Section: When not to use | Version: 5.2`. Mechanical,
  applied at build time, solves heading orphaning and most antecedent problems.
  Usually the highest return per unit of effort.
- **Put the warning inside the code block**, as a first-line comment, so it travels
  with the snippet wherever it is cut.
- **Bundle imports into every example.** Never a shared import block at page top.
- **Serve pre-chunked units from the MCP server.** This sidesteps third-party
  chunking for your own tooling. The docsite must still chunk well, because
  adopter teams will point their own pipelines at it.

#### Measuring it

Automated proxies for CI:

- % of chunks containing their component's name
- % of code chunks containing imports
- % of chunks containing an unresolved deictic (`this component`, `the above`,
  `it should`, `as mentioned`)
- % of anti-pattern blocks whose negation sits inside the block

Manual audit, worth doing once by hand: sample 30 random chunks, show each in
isolation, answer three questions — which component, what does it tell me to do,
is it a do or a don't. Score how many get all three. The first run is usually
sobering.

### 6.4 The hygiene eval set

**Mechanical — every PR, fully deterministic**

- Field presence, per component, per field
- Example compile pass rate (`tsc` on every extracted snippet)
- Example render pass rate (jsdom smoke test)
- Doc-vs-code prop drift, both directions
- Cross-surface reconciliation (Figma / React / catalog / docs), including variant
  name mismatches like `Size=Large` vs `size="lg"`
- Token reference validity: every token named in docs resolves
- Staleness delta: days between component source last commit and doc last commit
- Hedge word density per guidance section
- Chunk self-containment proxies

**Judged — weekly, small sample**

- Is each guidance statement rule-shaped or prose-shaped?
- Does each "when not to use" name a concrete alternative?
- Chunk-in-isolation comprehension
- Does the description use words an adopter would search for?

**Free ground truth you already have:** docsite search queries returning zero
results, and repeated questions in your support channel. Both are literal proof of
vocabulary gaps, already logged, no annotation required. If people keep asking
something the docs technically answer, that is a discoverability failure, not a
user failure.

### 6.5 Scoring — a matrix, not a number

Score per component per dimension, then assign a tier:

| Tier | Meaning |
|---|---|
| **A** | Safe for autonomous agent use |
| **B** | Usable, known gaps |
| **C** | Not agent-ready |

Put the tier in `catalog.json` and have the MCP server say so when serving a Tier C
component — *"guidance for this component is incomplete; verify prop usage against
source."* Being honest about your own data quality costs nothing and prevents
confident wrong output.

**Weight everything by usage.** Pull import frequency from consuming repos. The top
20 components likely cover 80% of real usage. Perfect hygiene across 200 components
is a multi-quarter project; excellent hygiene on 20 is a few weeks and buys most of
the benefit.

---

## 7. The tool surface

### 7.1 The always-loaded file

Generated by your CLI into the adopter's repo, pinned to their installed version,
regenerated on version bump. Target `AGENTS.md` by default; tool-specific paths as
options.

Budget yourself **~400 tokens** and force the trade-offs. A 3,000-token file gets
skimmed, and skimmed is the same as absent. What belongs in it:

- **Setup that fails silently** — required CSS imports, providers, and *what breaks
  without them*, not just what to do
- **Wrong priors, explicitly killed** — state what you are *not*. A model working
  in React will assume Tailwind or StyleX unless told otherwise, and that prior
  fires silently
- **The workflow protocol** — the required discovery sequence before writing UI, so
  lookups don't depend on the agent choosing to do them
- **Conditional retrieval triggers** — "read `docs layout` before writing any page"
- **Escalation ladders** — component props first, then `style`/`className` with
  tokens, never raw values. The agent needs to know what to do when option one
  fails, or it improvises
- **Compressed cross-component decisions** — "Dense data = rows, never Card-wrapped
  list items; Card is for standalone widgets." This is selection guidance hoisted
  into permanent context, which beats a compare tool because it applies whether or
  not the agent noticed it was confused
- **A specific self-check** — name the exact violations to hunt for. Generic
  "check your work" does nothing

### 7.2 MCP tools

Design around the agent's workflow, not your data model.

```
Discover → Decide → Specify → Compose → Validate ─┐
    ▲                                              │
    └──────────────── retry on failure ────────────┘
```

| Tool | Returns |
|---|---|
| `search_components(intent, context?, audience?)` | 3–5 ranked candidates, one line for and one against each |
| `get_component(name, version?)` | **Merged**: API, rules, schema, examples in one call |
| `compare_components(a, b, …)` | Disambiguation table: purpose, deciding question, rule of thumb |
| `find_pattern(description)` | Complete runnable composition with imports |
| `validate_code(source)` | Structured diagnostics with suggested fixes |
| `resolve_token(query)` | Bidirectional: intent → token, or raw value → nearest token / "none exists" |
| `resolve_design(figma_node)` | Component, prop mapping and tokens for that node |
| `check_migration(source, from, to)` | Mechanical change list |
| `report_gap(intent, tried)` | Tells the agent what to do when nothing fits; gives you a demand signal |

Resist going past a dozen tools — selection accuracy degrades as the list grows.

**Merge rather than split by source system.** Three tools keyed on component name
(`get_design_guidelines`, `get_api_usage_guide`, `get_component_schema`) means
three round trips, three chances at version skew, and one guaranteed failure mode:
the agent calls the API tool, sees a complete-looking answer, and never fetches the
guidelines.

**Add an intent entry point.** Tools keyed only on component name serve Specify and
nothing else. Discovery and Selection go unserved, so the agent guesses a name from
pretrained knowledge — and correct documentation for the wrong component is worse
than no answer, because nothing downstream flags it.

### 7.3 One engine, three entry points

Design-to-code maps Figma vocabulary onto code vocabulary. Migration maps v5 onto
v6. Validation maps written code onto the catalog and reports non-conformance.

All three are *translate between two vocabularies, then check conformance*. Build
one mapping engine parameterised by source vocabulary, target vocabulary and
conformance ruleset, and you get all three — plus the reconciliation job in
report-only mode. Build them separately and you will write the traversal and
diagnostics three times, and they will disagree.

### 7.4 Tool design rules

- **Return decisions, not documents.** A doc page is written for a human who will
  skim what's irrelevant. An agent pays full context price for every token and
  cannot skim. A 4,000-token response leaves budget for three components total.
- **Cap every response** at roughly 800 tokens. Beyond that, return a summary plus
  IDs and let the agent drill down.
- **Make errors teach.** `Unknown variant "ghost"` is a dead end.
  `Button has no "ghost" variant. Valid: primary, secondary, tertiary, destructive.
  For a low-emphasis action use "tertiary".` gets fixed next turn. Error strings
  are documentation delivered exactly when needed.
- **Pin to the adopter's version.** Docs for v5 against a repo on v3 produce code
  that looks right and fails at build.
- **Be fast and idempotent.** Agents call these in loops; over ~500ms is drag.
- **Offer a dense output mode** for anything a human might paste into a chat.

### 7.5 Serving designers

Designers don't work in a terminal, so an MCP server plus a CLI reaches none of
them. They need an MCP endpoint reachable from a chat client and a Figma plugin
answering in-canvas — same tools underneath, different clients.

Their questions are intent-shaped and pre-component: *what should I use for a
multi-step form, is there a pattern for empty states, does this exist or do I need
to design it?* That last one is why `report_gap` matters on the design side: it
tells you what's missing before someone builds a one-off.

`search_components` takes an `audience` parameter, or simply returns both facets.
Same intent layer, same ranking, same guidance — Figma names and variant properties
for one, React exports and props for the other.

### 7.6 What not to build

- A tool per component (explodes the tool list)
- `get_full_docs_page` (context bomb)
- A generic `search_docs` returning markdown chunks (a retrieval system wearing a
  tool costume)
- Design guidelines as long prose — the actionable parts are rules, and rules
  belong in `validate_code`, not in text to be read and hopefully remembered

---

## 8. Execution plan

The critical path, stripped to what has to happen.

### Phase 0 — the ground truth set (start now, blocks everything)

The bottleneck. Cannot be automated, borrowed or generated, and everything
downstream is worthless without it. Roughly two days of a senior engineer.

Write **30 tasks** with hand-authored expected answers — 12 single-component,
12 composed screens, 6 deliberately ambiguous — in one JSON file in a new
`vds-evals` repo.

```json
{
  "id": "t-012",
  "slice": "composed",
  "prompt": "Build a plan comparison section with three tiers, one marked recommended, and a sticky CTA at the bottom.",
  "expected_components": ["VdsCard", "VdsButton", "VdsBadge"],
  "forbidden_components": ["VdsModal"],
  "required_providers": ["VdsThemeProvider"],
  "notes": "Badge for the recommended marker, not a custom pill"
}
```

**Done when:** 30 tasks exist, each reviewed by a second engineer who agrees with
the expected answer. Disagreements are a finding in themselves — they mean your own
team has no shared answer.

### Phase 1 — the deterministic scorer (week 1–2)

A standalone Node package: source code in, structured diagnostics out.

1. **Hallucination check** — parse with `ts-morph` or `@babel/parser`, walk
   `JSXElement` nodes, collect element and attribute names, diff against
   `catalog.json`. Report unknown components, unknown props, invalid enum values.
2. **Typecheck** — write output into a scratch project with VDS installed, run
   `tsc --noEmit`.
3. **Token adherence** — scan for hex literals, raw px and font stacks in `style`
   props and className strings. Report count and ratio.
4. **Composition validity** — required providers present, mutually exclusive props
   not both set.
5. **Accessibility** — render in jsdom via testing-library, run axe-core, count
   critical violations.

**Build this as a library, not as eval code.** It is also `validate_code`, and
later the ESLint plugin and the CI gate. One engine, three surfaces. If those ever
disagree, adopters stop trusting all three.

**Done when:** you can pipe a `.tsx` file in and get six numbers out.

### Phase 2 — runner and first ablation (week 2)

A script taking a task and a config, producing scored output. Five configs, A–E
(see [Part 3](#3-proving-sufficiency)).

Three things that will otherwise cost you a week:

- **Run each task three times, report mean and spread.** Single runs are noisy
  enough that you'll chase phantom regressions.
- **Pin the model version.** Otherwise the eval measures model drift rather than
  data quality, and months of numbers become uncomparable.
- **Log every raw generation to disk.** You'll re-score them with rules you haven't
  written yet.

30 tasks × 5 configs × 3 runs = 450 generations. Cheap, and it gives you your first
real number.

**Done when:** you have a pass-rate table by config, and the A→D delta tells you
what your entire data investment is currently worth.

### Phase 3 — attribution and backlog (week 3)

Don't attribute 450 runs. Take config D only, single run, and tag every failure A–E
per [Part 4](#4-failure-attribution). That's 10–15 failures — an afternoon.

Sort by tag frequency. That is your data backlog, ranked by evidence rather than
opinion.

**Done when:** you can name the top three data gaps and point to the failing tasks
that prove each one.

### In parallel — hygiene instrumentation

Independent of the above, cheap, can run in the docs pipeline from day one. Field
presence; example compile pass rate; doc-vs-code prop drift; cross-surface
reconciliation; staleness delta; chunk self-containment proxies.

**Done when:** the hygiene matrix is published per component and nobody has fixed
anything yet. Resist fixing during measurement — you need the baseline.

### The deliverable

In a month you should be able to say:

> On 30 representative tasks, an agent with no VDS context scores X%. With
> `llms.txt` it scores Y%. With our MCP server it scores Z%. Hallucinated props are
> the largest failure category at N cases, and all of them trace to components
> lacking structured guidance. Fixing the top 20 components by import frequency
> should close most of it, and here is the ranked list.

That sentence is what gets funded, and what makes every subsequent decision
arguable on evidence.

### What to defer

Restructuring guidelines into records, templates, `AGENTS.md`, the design manifest.
All good, all should wait until the eval says which one matters most for *your*
system rather than in general. The scorer is the one exception, because it is
load-bearing for the eval itself.

Also resist expanding to 200 tasks. Thirty tasks run five ways and properly
attributed will teach you more than two hundred run once.

---

## 9. Traps

**Hygiene as a vanity metric.** 100% field presence alongside a 40% Layer 3 pass
rate means the fields are the wrong fields. Periodically correlate hygiene
dimensions against Layer 3 results: compare the hygiene profile of components that
pass against those that fail. If a dimension does not separate the two groups, drop
it from the rubric.

**Mirroring the docsite in the MCP server.** Documents are for humans who skim.
Tools are for agents who pay per token.

**Descriptive over decisional data.** Documenting what each component *is* while
leaving *which to choose*, *what not to do* and *how to compose* undocumented.
Selection and composition are where agents actually fall over.

**Two stores for two audiences.** They drift, and the join between them — which is
where design-to-code lives — becomes impossible.

**Rules behind tools.** Anything that must always apply cannot depend on the agent
deciding to fetch it.

**One aggregate score.** It always hides the components doing the damage.

---

## 10. Checklist

**Measurement**
- [ ] 30 eval tasks with hand-authored ground truth, peer-reviewed
- [ ] AST-based hallucination checker running
- [ ] `tsc` and token-adherence scorers running
- [ ] a11y and composition-validity checks running
- [ ] Ablation across configs A–E executed at least once
- [ ] Three runs per task, model version pinned, raw outputs logged
- [ ] Failure attribution tags applied to every miss
- [ ] Five-question knowledge probe written and shipped in onboarding

**Data**
- [ ] Derived fields generated, not authored
- [ ] Every example extracted from a compiling file
- [ ] Guidelines authored as records; docsite page rendered from them
- [ ] Every "when not to use" names an alternative (enforced field)
- [ ] Chunk breadcrumb prefixing at build time
- [ ] Anti-pattern warnings inside code blocks, not headings
- [ ] Cross-surface reconciliation report (Figma / React / catalog / docs)
- [ ] Figma↔code mapping manifest checked into the repo
- [ ] Component tiers published in `catalog.json`

**Delivery**
- [ ] `AGENTS.md` generated by CLI, version-pinned, under 400 tokens
- [ ] MCP tools merged by question, not split by source system
- [ ] Intent entry point (`search_components`) in front of name-keyed tools
- [ ] `validate_code` exposed via MCP, ESLint and CI from one engine
- [ ] Designer surface: chat-reachable MCP endpoint and/or Figma plugin
- [ ] `report_gap` capturing unmet needs from both audiences

**Ongoing**
- [ ] Hygiene dimensions correlated against Layer 3 results, rubric pruned
- [ ] Per-tool call counts logged by session
- [ ] Zero-result docsite searches reviewed as a vocabulary backlog
