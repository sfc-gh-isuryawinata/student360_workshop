# Student 360 for Higher Education: Build It, Govern It, Talk to It in CoWork

A hands-on workshop. Attendees unify six siloed campus systems into one governed **Student 360**, give it business meaning, lock it down for FERPA-style access, and put AI agents on top that advisors and analysts use in **CoWork** (Snowflake Intelligence).

It weaves in the production practices from the [CoWork Enterprise Guide](https://github.com/sfc-gh-jastaub/cowork_enterprise_guide): semantic-view best practices, four-layer access, PII handling, cost control, evaluation gates, agent-as-code and shared-account safety.

All data is **synthetic**. No real student records are used.

## The story

Lakeside University (about 2,000 students) loses students every year and finds out too late. The signals already exist, scattered across six systems that each call the student something different.

| Source | Owner | Student key | Signal |
|---|---|---|---|
| SIS | Registrar | `S0000123` | Demographics, college, major, GPA, course grades |
| LMS | Academic Technology | login email (mixed case, legacy domain) | Weekly logins, submissions, scores |
| Financial Aid | Financial Aid Office | `FA-100007` and bare number `123` | Aid package, unmet need, SAP status |
| Bursar | Student Accounts | `S0000123` | Balance, days past due, holds |
| Advising CRM | Advising Center | `C-123` and `STU-0000123` | Advisor, **free-text notes** (contain PII) |
| Campus ID card | Card Office | card id, joined by email | Library, rec, dining, events |

## What attendees build

```
 RAW (6 sources)            CURATED                         SEMANTIC / AGENTS                 CoWork
 ----------------   ->   ----------------------   ->   ---------------------------   ->   ------------------
 SIS  LMS  FinAid        STUDENT_XWALK (identity)       STUDENT_360_SV (semantic view)    Advisor Assistant
 Bursar CRM  Card        FEAT_* (5 dynamic tables)      Cortex Search: names, notes       (Engineering only)
                         ADVISING_NOTE_ENRICHED         2 agents + eval + budget          Student Success
                           (AI_REDACT + AI_CLASSIFY)    GOVERNANCE: row + column policy   Analyst (institution)
                         STUDENT_360 (1 row/student)
```

## Notebooks

Run **00 to 05 in order**, then **06** (cleanup) last. Each notebook is a SQL notebook and builds on the previous one.

| # | Notebook | Min | What attendees do |
|---|---|---|---|
| 00 | `Notebook_00_Lab_Setup` | 20 | Isolated role, database, schemas, XS warehouse; load six messy source systems |
| 01 | `Notebook_01_Build_Student360` | 40 | Resolve identity (exact + fuzzy) with a match-rate report; five incremental dynamic-table feature sets; `AI_REDACT` + `AI_CLASSIFY` on advising notes; assemble `STUDENT_360` with an explainable risk score |
| 02 | `Notebook_02_Context_Layer` | 35 | Fuzzy-name and notes Cortex Search services; governed semantic view (descriptions, synonyms, metrics, custom instructions, verified queries); validate with `SEMANTIC_VIEW()` |
| 03 | `Notebook_03_Govern_Access` | 35 | Two persona roles, four-layer grants, row access by college, PII masking, FERPA tags; prove it by switching roles; the Cortex Search owner's-rights gotcha and its fix |
| 04 | `Notebook_04_Build_Agent_Harden` | 40 | Two agents from one pattern; layer-2 grants; test each persona and a guardrail; cost tags, timeout, budget, per-user quota |
| 05 | `Notebook_05_Evaluate_Publish_CoWork` | 40 | Evaluation dataset with a refusal case; scored go-live gate; capture the spec; publish to CoWork; try it as each persona |
| 06 | `Notebook_06_Cleanup` | 5 | Remove only the lab's objects; verify the shared CoWork object is intact |

Total: about 3.5 hours of hands-on, plus a short intro. For a half-day, run 00 as pre-work (or pre-load it) and spend the time on 01 to 05.

## Prerequisites

- A Snowflake account with `ACCOUNTADMIN` (for account-scoped steps: roles, publishing to CoWork).
- Cortex AI features available in the region, with cross-region inference allowed (Notebook 00 sets it; it is a no-op if already on).
- Snowflake Intelligence (CoWork) enabled for the account.
- Cortex Agents, Cortex Search, `AI_REDACT`, `AI_CLASSIFY`, dynamic tables and semantic views available.
- Optional: the [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli/index) to upload the evaluation YAML (or use the Snowsight upload UI).

## Running the notebooks

**Git-connected Workspace (recommended):** Snowsight → Projects → Workspaces → *From Git repository* → paste this repo's URL → open `notebooks/`. Run each on the SQL kernel with warehouse `STUDENT360_LAB_WH` (created in Notebook 00; use any warehouse for the first run).

**Manual upload:** upload each `notebooks/*.ipynb` through Snowsight (Projects → Notebooks → Import .ipynb).

**Evaluation YAML (Notebook 05):** upload `eval/agent_eval.yaml` to `@STUDENT360_LAB.AGENTS.EVAL_CONFIG`:
```bash
snow stage copy eval/agent_eval.yaml @STUDENT360_LAB.AGENTS.EVAL_CONFIG --overwrite
```

## Best practices woven in

| Practice (from the CoWork Enterprise Guide) | Where |
|---|---|
| Isolated namespace, one role, removable as a unit | 00, 06 |
| Raw / curated / serving / governance separation; no grants on RAW | 00, 03 |
| Descriptions as the #1 accuracy input; synonyms; metrics own the math | 02 |
| Verified queries from real questions | 02 |
| Two kinds of custom instructions (SQL generation vs question categorization) | 02 |
| Fuzzy literal matching for identifier columns | 02 |
| One semantic view vs many; when to look at ontology | 02 |
| Validate the semantic view *before* building the agent | 02 |
| Four-layer access model | 03, 04 |
| PII removed at the data layer, not in the prompt | 01, 03 |
| Least exposure: leave PII out of the semantic view | 02 |
| Agent budget (tokens, seconds) and routing instructions | 04 |
| Observe, attribute, control: usage view, tags, timeout, budget, quota | 04 |
| Negative tests, scored evaluation, go-live threshold | 05 |
| Agent-as-code: capture the spec | 05 |
| Shared-singleton safety: add and remove only your own agents | 05, 06 |

The reference guide also covers dev-to-prod promotion and a continuous-improvement loop (mining traces, curating evals, optimising instructions). They are a natural follow-on to Notebook 05.

## Facilitator notes: gotchas this workshop surfaces on purpose

These came out of testing the lab end to end. Each is a teachable moment, and each is written into the notebooks.

1. **Secondary roles silently widen access.** A session with `SECONDARY ROLES ALL` (the default) keeps `ACCOUNTADMIN` privileges even after `USE ROLE <persona>`, so a "negative test" passes for the wrong reason. All persona tests run `USE SECONDARY ROLES NONE`. (Notebooks 03, 04)
2. **Cortex Search runs with owner's rights.** Row access policies on the source table do **not** scope the search service. Notebook 03 proves the leak, then fixes it with a per-audience index. Query-time filters are conveniences, not controls.
3. **A row access policy with a subquery disables change tracking.** That breaks dynamic tables and Cortex Search services that read the table. The lab uses an expression policy with a role-name convention instead. (Notebook 03, Step 2)
4. **Dynamic table refresh mode.** `REFRESH_MODE = INCREMENTAL` is declared explicitly on the feature tables and `STUDENT_360`; the identity crosswalk is a plain table because a many-way outer join is not incremental. Cortex Search needs change tracking on its source. (Notebook 01)
5. **Statement timeout and re-runs.** Notebook 04 sets a 300-second warehouse timeout. It is set high enough that re-running the `AI_CLASSIFY` enrichment in Notebook 01 still completes.
6. **The CoWork object is shared.** Another team's agent may already be published. Never drop or replace the object; only `ADD`/`DROP` your own agents.
7. **Branding is account-wide**, so it is shown as reference SQL only.

### Suggested talk track (5 minutes per beat)

1. *The problem:* six systems, six student keys. Run the "same student, six keys" query in Notebook 00.
2. *The 360:* show `TOP_RISK_DRIVERS`. The score is explainable, so an advisor can act on it.
3. *The trust moment:* the same query as two roles returns different rows and masked columns (Notebook 03). Then show the owner's-rights leak.
4. *The payoff:* ask the Advisor Assistant in CoWork who to reach out to first, then ask for an email address and watch it decline.
5. *The discipline:* the evaluation gate, with a refusal test in the set.

### Extension ideas

- Replace the rule-based score with a Snowflake ML classification model trained on prior-year outcomes.
- Add a data-metric function that alerts when the identity match rate drops.
- Add an *admissions funnel* semantic view as a second tool and discuss one-vs-many views.
- Stamp out one advisor agent per college from the captured spec.
- Use a stream and task so only new advising notes are sent to `AI_CLASSIFY` / `AI_REDACT`.

## Cost

Everything runs on an XS warehouse that auto-suspends after 60 seconds. The Cortex costs are the two AI functions over about 3,000 short notes (Notebook 01), five or six agent calls, and a four-question evaluation. Agent reasoning is serverless and billed separately. The budget and quota in Notebook 04 are created in monitoring mode so they never block or email anyone on a shared account.

## Regenerating the notebooks

The notebooks are generated by `build/`. Edit the `build/nbNN.py` files and run:

```bash
cd build && python3 build.py          # rebuild all
python3 build.py nb03                  # rebuild one
```

`build/run.py` is the test harness used to verify every SQL cell against a live account:

```bash
python3 run.py ../notebooks/Notebook_00_Lab_Setup.ipynb <snow_connection_name> [skip_cells_csv]
```

## Verification status

Notebooks 00 to 06 were run end to end against a live Snowflake account from a clean state: raw data loaded, identity match rates computed, all dynamic tables incremental, semantic view validated against source, fuzzy name search resolved a misspelled name, both agents answered as their personas, negative access tests behaved as expected, the evaluation gate passed, both agents published to and removed from the shared CoWork object, and the account was left clean.
