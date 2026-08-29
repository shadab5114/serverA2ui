# Design System AI Readiness — Framework and Working Doc

A practical framework for measuring whether a design system's data is good enough
for AI agents, and for improving it in a way that can be proven rather than
asserted.

---

## 1. Premise

**AI readiness is not a property of your assets. It is a measured success rate on
real tasks.**

A doc site does not have a readiness score any more than a hammer has one. The
question "do I have enough data?" cannot be answered by auditing the data. It can
only be answered by giving an agent realistic work, measuring what fraction it
gets right, and diagnosing what specifically broke.

This reframes the whole exercise as a loop:

```
define tasks -> run agents -> score -> attribute each failure to a data gap
   -> fix the data -> re-run
```

Everything below is machinery for running that loop.

---

## 2. The readiness stack

Five layers. Lower layers are cheap and deterministic; upper layers are slow and
realistic. Run them all, but weight your attention by what fails.

### Layer 0 — Data hygiene
Structural checks on the data itself. Runs in CI on every change.
Necessary but not sufficient. Covered in depth in section 7.

### Layer 1 — Discovery
*Can the agent find the right thing?*

Build ~150 queries written the way a product engineer talks, not the way your
docs are titled. "dropdown", "picker", "select box", "let the user choose one of
a list" should all resolve to the same component. Record the correct answer by
hand. Measure **recall@5**.

This is where design systems with distinctive internal naming fail silently.
Docs are indexed by internal names; users search by intent. The fix is synonym
and intent metadata in the catalog, not a better search engine.

### Layer 2 — Selection
*Did it pick the right component?*

Give an intent, not a name. "User needs to pick a date range for a bill cycle."
Ask which component(s). Compare to what your best design system engineer would
answer. Score exact match plus acceptable alternative.

Agents fail here more than anywhere else. Not because they cannot write JSX, but
because nothing in the data answers *Modal vs Drawer vs inline panel* or *Toast
vs Banner vs inline error*. Per-component documentation structurally cannot
answer a cross-component question.

### Layer 3 — Generation
*Does the produced code compile and comply?*

**For a design system, most of this scoring can be deterministic.** You have
TypeScript, a real component library, and a catalog. Use the compiler as the
judge instead of an LLM.

| Metric | How | Why it matters |
|---|---|---|
| Hallucination rate | Parse output to AST; check every JSX element and prop against the catalog | The single most honest readiness signal you have |
| Typecheck pass | `tsc` | Binary, no argument |
| Token adherence | Count raw hex / px / font stacks where a token exists | Measures whether design intent survives |
| Composition validity | Required providers present? Mutually exclusive props both set? | Catches structural misuse |
| Accessibility | Render in jsdom, run axe, count critical violations | Non-negotiable output quality |
| Visual diff | Compare against reference implementation | Expensive; add last |

Six numbers, all objective, all runnable on every docs change.

### Layer 4 — End-to-end
*Can it build a whole screen?*

Multi-turn, realistic tasks. "Build a plan comparison page with three tiers and a
sticky CTA." Rubric-scored with human spot checks. Keep this set small (10–15
tasks) — it is slow, but it is the only layer that catches composition-scale
problems.

---

## 3. Proving sufficiency: the ablation method

This is how you move from "I think the data is good" to "I can show what each
asset is worth."

Run the **same eval set** under different data configurations:

| Config | Setup |
|---|---|
| A | No design system context at all (plain React knowledge) |
| B | `llms.txt` only |
| C | Full docs in context |
| D | MCP tools enabled |
| E | MCP tools + validator tool |

The **deltas** are the evidence.

- If D beats B by only two points, your MCP server is not earning its cost.
- If A already scores 60%, your bar is higher than you assumed and your headline
  number is flattering you.
- If E is the only config that clears your gate, validation is doing the work,
  not documentation.

This turns "is my data good?" from an opinion into a measurement.

### Setting baselines

There is no industry standard number to hit. Use two anchors:

- **Floor:** Config A above.
- **Ceiling:** A senior design-system-fluent engineer doing the same tasks.
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

---

## 4. Failure attribution

Every failed case gets exactly one tag. This is what converts eval scores into a
prioritised data backlog.

| Tag | Meaning | Owner |
|---|---|---|
| **A. Not findable** | The information exists, retrieval missed it | You |
| **B. Ambiguous** | Retrieval found several things and picked wrong | You |
| **C. Not specified** | Right doc found, doesn't answer the question | You |
| **D. Found and ignored** | Doc says it, but buried in prose the agent skimmed | You |
| **E. Model limitation** | Nothing in your data would have helped | Not you |

Tag D matters more than people expect. If a rule lives in paragraph nine of a
page, it effectively does not exist for an agent. That is a formatting fix, not a
content fix.

---

## 5. Starting task set

Do not build 500 tasks. Build 30 and run them well.

| Slice | Count | Purpose |
|---|---|---|
| Single component | 12 | API correctness, prop hallucination |
| Composed screen | 12 | Composition, provider requirements, token usage |
| Deliberately ambiguous | 6 | Selection quality, disambiguation data |

Write the expected answers by hand. This is the expensive part and there is no
shortcut; hand-written ground truth is what makes every subsequent run cheap.

---

## 6. MCP tool surface for adopters

The MCP server is not a documentation API. It is the set of moves an agent makes
while building a screen. Design tools around that loop, not around your data
model.

```
Discover -> Decide -> Specify -> Compose -> Validate -> (loop back on failure)
```

### The tools worth building

| Tool | Returns | Notes |
|---|---|---|
| `search_components(intent, context?)` | 3–5 ranked candidates, each with one line for and one against | Takes a plain sentence, not a name. `context` should change ranking. |
| `compare_components(a, b, ...)` | Small disambiguation table: purpose, deciding question, rule of thumb | Exists because the answer lives *between* two doc pages |
| `get_component_api(name, version?)` | Structured props: type, default, required, allowed values, deprecation | Serialized schema, not prose |
| `get_usage_guidance(name)` | When to use, when not to, top three mistakes, required a11y behaviour | Short and imperative. If it reads like a page, it's too long. |
| `find_pattern(description)` | Complete runnable composition with imports | Highest-value content gap for most design systems |
| `validate_code(source)` | Structured diagnostics with suggested fixes | **Build this first.** See below. |
| `resolve_token(query)` | Bidirectional: intent → token, or raw value → nearest token / explicit "none exists" | Reverse direction is what kills hardcoded values |
| `report_gap(intent, tried)` | Acknowledgement | Tells the agent what to do when nothing fits; gives you a live demand signal |
| `check_migration(code, from, to)` | Mechanical change list | Agents apply these well once told exactly what they are |

Roughly nine tools. Resist going past a dozen — tool-selection accuracy degrades
as the list grows, and thirty narrow tools means the agent spends its reasoning
picking a tool instead of solving the problem.

### Why `validate_code` comes first

It should catch: nonexistent components, nonexistent props, invalid prop
combinations, missing required providers or parents, hardcoded values where a
token exists, deprecated APIs, a11y violations.

Two things make it disproportionately valuable:

1. **It closes the loop.** The agent self-corrects instead of shipping a
   confident hallucination.
2. **It is the same rules engine you need for the Layer 3 scorer.** One build,
   three surfaces: MCP tool for agents, ESLint plugin for editors, CI gate for
   pipelines. If those three ever disagree, adopters stop trusting all three.

### Tool design rules that matter more than the tool list

- **Return decisions, not documents.** A doc page is written for a human who will
  skim what is irrelevant. An agent pays full context price for every token and
  cannot skim. A 4,000-token response leaves budget for three components total.
- **Cap every response** at roughly 800 tokens. If more is genuinely needed,
  return a summary plus IDs and let the agent drill down.
- **Make errors teach.** `Unknown variant "ghost"` is a dead end.
  `Button has no "ghost" variant. Valid: primary, secondary, tertiary,
  destructive. For a low-emphasis action use "tertiary".` gets fixed next turn.
  Error strings are documentation delivered exactly when needed.
- **Pin to the adopter's version.** Docs for v5 against a repo on v3 produce code
  that looks right and fails at build. Accept a version argument or detect from
  `package.json`.
- **Be fast and idempotent.** Agents call these in loops. Over ~500ms is visible
  drag.

### What not to build

- A tool per component (explodes the tool list)
- `get_full_docs_page` (context bomb)
- A generic `search_docs` returning markdown chunks (a retrieval system wearing a
  tool costume)
- Anything returning design guidelines as long prose — the actionable parts are
  rules, and rules belong in `validate_code`, not in text to be read and hopefully
  remembered

---

## 7. Layer 0 deep dive: data hygiene

### 7.1 Perspective — completeness is not the thing being measured

The default approach is a checklist: does every component have a description, a
props table, an example, a11y notes? The number goes up, everyone feels good, and
Layer 3 pass rates do not move.

Presence and usefulness are different properties. Grade each field along six
dimensions instead of one:

| Dimension | Question |
|---|---|
| **Presence** | Does it exist? |
| **Correctness** | Does it match what the code actually does? |
| **Consistency** | Do Figma, React, tokens, docs, and the catalog agree? |
| **Actionability** | Is it a rule an agent can apply, or prose a human interprets? |
| **Discoverability** | Does it use the words adopters use, or internal names? |
| **Freshness** | Has it drifted since the code changed? |

Most design systems score well on 1 and badly on 3, 4, and 5. Those three are
where agent failures actually come from.

### 7.2 Strategy — the derived / authored split

The single decision that determines whether hygiene is sustainable or a
treadmill.

Anything typed by hand will drift. Not might — will. So the first move is not to
improve docs but to **classify every field as derived or authored, then shrink
the authored set as far as it will go.**

**Derived — regenerate, never edit**

- Prop types, defaults, required flags
- Token names and values
- Component and variant lists
- Runnable examples
- Version and deprecation state

**Authored — write once, then test**

- When to use / when not to use
- Which alternative to use instead
- Composition recipes
- Synonyms and intent phrasing
- Known anti-patterns

Two consequences:

**On the derived side, hygiene stops being a content problem and becomes a build
problem.** A hand-maintained props table has a decay rate. One generated from
TypeScript types has none. Same for examples: a code fence typed into markdown is
already partly broken and nobody knows which parts. Examples extracted from real
files that compile and render in CI make that number structurally zero.

**On the authored side is the uncomfortable part.** The fields that matter most to
an agent — which component to pick, what not to do, how things compose — are
exactly the ones that cannot be generated. Human effort previously spent on prop
tables should move there. Not more work; relocated work.

### 7.3 Making authored content rule-shaped

> Consider using Drawer when you have a lot of content.

versus

> Use Drawer when content requires scrolling or exceeds the modal max height of
> 480px. Otherwise use Modal.

The first is prose a human interprets with judgement. The second is a condition an
agent evaluates. Both are "present". Only one is usable.

Two cheap tests:

1. **Hedge density.** Grep for *generally, typically, consider, it's recommended,
   may want to, in most cases*. High density is a reliable smell.
2. **Does every "when not to use" name a specific alternative component?** This is
   possibly the highest-value single check in the whole hygiene set. A
   prohibition with no exit leaves the agent with nowhere to go, and it will
   invent something. "Don't use Modal for long forms" is a dead end. "Don't use
   Modal for long forms — use a full-page route" is a decision.

### 7.4 The sleeper issue — chunk integrity

**The agent never reads your documentation page.**

A retrieval system slices every page into pieces of a few hundred tokens, embeds
each as a vector, and at query time returns the closest three or four. The agent
sees those fragments and nothing else. No page, no scroll, no heading above.

Mental image: someone tears the docs into index cards, shuffles them, and deals
the agent five. Every card must stand on its own.

#### Failure modes

| Mode | What happens |
|---|---|
| **Orphaned negation** | "Don't do this" heading in chunk A, the code in chunk B. The agent gets clean anti-pattern code from an authoritative source with nothing warning against it. Most dangerous — the docs actively teach the wrong thing. |
| **Heading orphaning** | Component name appears once in the H1. Every chunk below is about "the `size` prop" with no indication whose. Most widespread. |
| **Split rules** | Condition in one chunk, consequence in the next. Half a rule is worse than none. |
| **Lost antecedents** | "It must be wrapped in a provider." "This component requires a label." "As mentioned above." In a fragment, "it" refers to nothing. |
| **Decapitated tables** | Props table split mid-body loses its header row. `variant \| string \| "primary"` with no idea which column is which. |
| **Examples without imports** | Snippet in one chunk, import block in another. The agent guesses import paths — a common source of hallucinated imports. |
| **Inherited context stated once** | "All form components require `FormProvider`" at the top of a family page. Forty component chunks below carry none of it. |

#### Why it hits twice

Chunk integrity is not only a comprehension problem. Chunks are embedded as
vectors. A chunk that does not contain the word "Button" matches weakly against a
query about Button. Heading orphaning therefore degrades **Layer 1 recall** as
well as **Layer 3 correctness**. Fixing it moves both numbers.

And unlike a human who lands mid-page and scrolls up, an agent cannot scroll up
and will not ask. It fills the gap with plausible invention — which, in a design
system context, is indistinguishable from correct code until it hits the build.

#### Fixes

- **Repeat instead of referencing.** The mindset flip. Human docs optimise for DRY
  — say it once, link to it. Agent docs optimise for chunk independence. If forty
  components need `FormProvider`, that line belongs on all forty pages.
  Redundancy that feels sloppy to a technical writer is what makes each fragment
  survive alone.
- **Chunk deliberately, not by character count.** Because docs are generated from
  the catalog, you control where cuts land. Emit explicit boundaries at semantic
  units — one rule, one example, one section — rather than letting a splitter cut
  at 512 tokens. Most teams do not have this option.
- **Prefix every chunk with breadcrumbs** before embedding:
  `Component: Button | Section: When not to use | Version: 5.2`. Purely
  mechanical, applied at build time. Solves heading orphaning and most antecedent
  problems in one move. Usually the highest return per unit of effort.
- **Put the warning inside the code block**, as a first-line comment, not in the
  heading above it. Then it travels with the snippet wherever it is cut.
- **Bundle imports into every example.** Always. Never a shared import block at
  the top of a page.
- **Serve pre-chunked units from the MCP server.** This sidesteps third-party
  chunking for your own tooling. The docsite must still chunk well, because
  adopter teams will point their own pipelines at it and you will not control
  that.

#### Measuring it

Automated proxies for CI:

- % of chunks containing their component's name
- % of code chunks containing imports
- % of chunks containing an unresolved deictic (`this component`, `the above`,
  `it should`, `as mentioned`)
- % of anti-pattern blocks whose negation sits inside the block

Manual audit, worth doing by hand once: sample 30 random chunks, show each in
isolation, answer three questions — which component is this about, what does it
tell me to do, is it a do or a don't. Score how many get all three. The first run
is usually sobering.

### 7.5 The hygiene eval set

**Mechanical — every PR, fully deterministic**

- Field presence, per component, per field
- Example compile pass rate (`tsc` on every extracted snippet)
- Example render pass rate (jsdom smoke test)
- Doc-vs-code prop drift, both directions
- Cross-surface reconciliation: set difference between Figma component names,
  React exports, catalog entries, and doc pages — plus variant name mismatches
  (`Size=Large` vs `size="lg"`)
- Token reference validity: every token named in docs resolves
- Staleness delta: days between component source last commit and doc last commit
- Hedge word density per guidance section
- Chunk self-containment heuristics (see 7.4)

**Judged — weekly, small sample, LLM or human**

- Is each guidance statement rule-shaped or prose-shaped?
- Does each "when not to use" name a concrete alternative?
- Chunk-in-isolation comprehension
- Does the description use words an adopter would search for?

**Free ground truth you probably already have:** docsite search queries that
returned zero results, and repeated questions in your support channel. Both are
literal proof of vocabulary gaps, already logged, no annotation required. If
people keep asking something the docs technically answer, that is a
discoverability failure, not a user failure.

### 7.6 Scoring — a matrix, not a number

Do not aggregate to one figure; it hides exactly the components that need work.
Score per component per dimension, then assign a tier:

| Tier | Meaning |
|---|---|
| **A** | Safe for autonomous agent use |
| **B** | Usable, known gaps |
| **C** | Not agent-ready |

Then do something slightly unusual: put the tier in `catalog.json`, and have the
MCP server say so when serving a Tier C component — *"guidance for this component
is incomplete; verify prop usage against source."* Being honest about your own
data quality costs nothing and prevents confident wrong output.

**Weight everything by usage.** Pull import frequency from consuming repos. The
top 20 components likely cover 80% of real usage. Perfect hygiene across 200
components is a multi-quarter project; excellent hygiene on 20 is a few weeks and
buys most of the benefit.

---

## 8. Rollout

| Phase | Action | Why |
|---|---|---|
| 1 | **Measure everything, fix nothing.** Publish the hygiene matrix as-is. | Without a genuine baseline, no later improvement is provable |
| 2 | **Automate the derived side.** Kill hand-maintained prop tables and snippets. | Usually a large jump on its own, and it stops future decay |
| 3 | **Author intent content for the top 20 by usage.** | Where the agent-facing value actually is |
| 4 | **Build `validate_code`.** | Closes the agent loop and gives you the Layer 3 scorer for free |
| 5 | **Gate.** No new component below Tier B; no regressions on existing ones. | Prevents the debt from regrowing |
| 6 | **Correlate.** Check hygiene dimensions against Layer 3 results; prune the rubric. | Validates the rubric itself |

A reasonable first two weeks: 30 tasks with hand-written ground truth, the AST
hallucination checker plus `tsc` plus token adherence scorer, and the ablation run
across configs A–D. That produces one real number and a ranked list of what is
broken.

---

## 9. Traps

**Hygiene as a vanity metric.** 100% field presence alongside a 40% Layer 3 pass
rate means the fields are the wrong fields. The dashboard goes green while nothing
improves. Guard against this by periodically correlating hygiene scores against
downstream eval results: compare the hygiene profile of components that pass
Layer 3 against those that fail. If a dimension does not separate the two groups,
drop it from the rubric.

**Mirroring the docsite in the MCP server.** The instinct is to make each tool an
endpoint. Documents are for humans who skim. Tools are for agents who pay per
token.

**Descriptive over decisional data.** Documenting what each component *is*, while
leaving *which to choose*, *what not to do*, and *how to compose* undocumented.
Selection and composition are where agents actually fall over.

**Disconnected Figma.** If the design library only lives in Figma, there is no
identity chain from Figma node → React component → doc page → token, and any
design-to-code use case has a hard ceiling. The agent is guessing from visual
appearance.

**One aggregate score.** It always hides the components doing the damage.

---

## 10. One-page checklist

- [ ] 30 eval tasks written with hand-authored ground truth
- [ ] AST-based hallucination checker running
- [ ] `tsc` and token-adherence scorers running
- [ ] Ablation across configs A–D executed at least once
- [ ] Failure attribution tags applied to every miss
- [ ] Derived fields generated, not authored
- [ ] Every example extracted from a compiling file
- [ ] Cross-surface reconciliation report (Figma / React / catalog / docs)
- [ ] Chunk breadcrumb prefixing at build time
- [ ] Anti-pattern warnings inside code blocks
- [ ] Every "when not to use" names an alternative
- [ ] Component tiers published in `catalog.json`
- [ ] `validate_code` exposed via MCP, ESLint, and CI from one engine
- [ ] Hygiene dimensions correlated against Layer 3 results
