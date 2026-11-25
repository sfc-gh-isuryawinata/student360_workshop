from lib import NB, DB, ROLE, WH

ADV = "STUDENT360_LAB_ADVISOR_ENGINEERING"
IR = "STUDENT360_LAB_IR_ANALYST"

n = NB("Notebook_03_Govern_Access.ipynb", 3, "Govern Access (FERPA-style)", "Phase 3 - Control who sees what", 35)
n.header([
    "🛠️ Creates two **CoWork-only consumer roles** with different data entitlements (a college-scoped advisor and an institution-wide IR analyst)",
    "🛠️ Grants the **four independent layers** of access an agent needs at runtime",
    "🛠️ Enforces **row-level scope by college** with a row access policy and a mapping table",
    "🛠️ Enforces **column-level PII masking** with a masking policy, and classifies columns with tags",
    "🛠️ Demonstrates - and fixes - the **Cortex Search owner's-rights gotcha**",
],
    "In higher education the data is regulated (FERPA in the US; GDPR/local equivalents elsewhere). The single most important property of an AI agent is that it **can never see more than the person asking is allowed to see**. Snowflake enforces that on the *data*, so it holds no matter what the prompt says.",
    "Notebook 02")

n.md("""> 📌 **Not legal advice.** FERPA permits school officials with a *legitimate educational interest* to see education records. This notebook shows the **technical controls** that implement that principle; your registrar and counsel decide who qualifies.

## 🎓 Design: who sees what

| Role | Who it represents | Rows | PII (email, phone, DOB) | Agent |
|---|---|---|---|---|
| `STUDENT360_LAB_ADVISOR_ENGINEERING` | An academic advisor in the College of Engineering | **Engineering only** | Visible (needed to contact their own students) | Advisor Assistant |
| `STUDENT360_LAB_IR_ANALYST` | Institutional Research analyst | **All colleges** | **Masked** (aggregate analysis needs no contact info) | Student Success Analyst |

Same agent code, same semantic view - **different answers**, because the data layer decides.""")

n.sql("set_context", "Set Context", f"""
USE ROLE ACCOUNTADMIN;
USE DATABASE {DB};
USE WAREHOUSE {WH};
SELECT CURRENT_ROLE(), CURRENT_DATABASE();
""")

n.md("""## Step 1: Create the Consumer Roles + the Four-Layer Grants

Running an agent needs **four independent layers** of access. Missing any one gives a confusing failure:

| Layer | What | Grant |
|---|---|---|
| **1. Platform** | Use Cortex + compute | `SNOWFLAKE.CORTEX_USER` (or `CORTEX_AGENT_USER`), `USAGE` on warehouse + database + schema |
| **2. Agent** | Use *this* agent | `USAGE ON AGENT` (granted in Notebook 04, after the agent exists) |
| **3. Tools** | Use the agent's tools | `USAGE` on the semantic view and search services |
| **4. Data** | Read the underlying data | `SELECT` on the curated tables (policies apply automatically) |

✅ **Note what is missing:** **no grant on `RAW`**. The agent's roles can never reach un-redacted notes or source-system tables.""")
n.sql("four_layer_grants", "Roles and four-layer grants", f"""
USE ROLE ACCOUNTADMIN;
CREATE ROLE IF NOT EXISTS {ADV} COMMENT = 'Advisor (Engineering): CoWork-only consumer, Engineering rows, PII visible';
CREATE ROLE IF NOT EXISTS {IR}  COMMENT = 'Institutional Research analyst: CoWork-only consumer, all rows, PII masked';
-- Let the lab admin (and ACCOUNTADMIN) switch into them to test
GRANT ROLE {ADV} TO ROLE {ROLE};
GRANT ROLE {IR}  TO ROLE {ROLE};
GRANT ROLE {ADV} TO ROLE ACCOUNTADMIN;
GRANT ROLE {IR}  TO ROLE ACCOUNTADMIN;

-- Layer 1: platform entitlement + compute
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE {ADV};
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE {IR};
GRANT USAGE ON WAREHOUSE {WH} TO ROLE {ADV};
GRANT USAGE ON WAREHOUSE {WH} TO ROLE {IR};
GRANT USAGE ON DATABASE {DB} TO ROLE {ADV};
GRANT USAGE ON DATABASE {DB} TO ROLE {IR};

-- Layer 3: tool / resource access (semantic view + search services)
GRANT USAGE ON SCHEMA {DB}.SEMANTIC TO ROLE {ADV};
GRANT USAGE ON SCHEMA {DB}.SEMANTIC TO ROLE {IR};
GRANT USAGE ON SCHEMA {DB}.AGENTS   TO ROLE {ADV};
GRANT USAGE ON SCHEMA {DB}.AGENTS   TO ROLE {IR};
GRANT SELECT ON SEMANTIC VIEW {DB}.SEMANTIC.STUDENT_360_SV TO ROLE {ADV};
GRANT SELECT ON SEMANTIC VIEW {DB}.SEMANTIC.STUDENT_360_SV TO ROLE {IR};
GRANT USAGE ON CORTEX SEARCH SERVICE {DB}.AGENTS.STUDENT_NAME_SEARCH TO ROLE {ADV};
GRANT USAGE ON CORTEX SEARCH SERVICE {DB}.AGENTS.STUDENT_NAME_SEARCH TO ROLE {IR};
-- (the notes search service is granted deliberately in Step 5, after the owner's-rights discussion)

-- Layer 4: data access on the CURATED layer only (policies still apply)
GRANT USAGE ON SCHEMA {DB}.CURATED TO ROLE {ADV};
GRANT USAGE ON SCHEMA {DB}.CURATED TO ROLE {IR};
GRANT SELECT ON ALL TABLES         IN SCHEMA {DB}.CURATED TO ROLE {ADV};
GRANT SELECT ON ALL TABLES         IN SCHEMA {DB}.CURATED TO ROLE {IR};
GRANT SELECT ON ALL DYNAMIC TABLES IN SCHEMA {DB}.CURATED TO ROLE {ADV};
GRANT SELECT ON ALL DYNAMIC TABLES IN SCHEMA {DB}.CURATED TO ROLE {IR};
GRANT SELECT ON ALL VIEWS          IN SCHEMA {DB}.CURATED TO ROLE {ADV};
GRANT SELECT ON ALL VIEWS          IN SCHEMA {DB}.CURATED TO ROLE {IR};
-- Layer 2 (USAGE ON AGENT) is granted in Notebook 04.
SELECT 'Consumer roles created with layers 1, 3 and 4' AS STATUS;
""")

n.md("""### 📌 Reference only - production hardening (not run in this lab)

For a controlled rollout, restrict Cortex to the intended roles instead of everyone:

```sql
REVOKE DATABASE ROLE SNOWFLAKE.CORTEX_USER FROM ROLE PUBLIC;
GRANT  DATABASE ROLE SNOWFLAKE.CORTEX_AGENT_USER TO ROLE <advisor_role>;   -- Agents API only, not every Cortex feature
```
Pair the role with `ALTER USER <u> SET ALLOWED_INTERFACES = ('SNOWFLAKE_INTELLIGENCE')` to confine a business user to the CoWork chat (no worksheets, no SQL) - we do exactly that for a test user in Notebook 05. Account-level identity hardening (SSO/SCIM, MFA, network policies, PrivateLink) belongs in the customer's own account checklist.

### 🔹 What the agent's SQL can reach

Agents generate SQL as the **caller's role**. They can read any object that role can `SELECT` - not only the tables in the semantic view. They are still constrained by RBAC, by the semantic view (which steers generated SQL), and by orchestration instructions. **For strict scoping**, grant the consumer role only the objects you want reachable (as above) and rely on row/column policies for the rest.""")

n.md("""## Step 2: Row-Level Scope by College

🛠️ One row access policy decides, per row, whether the current role may see it. We use a **naming convention**: a role named `STUDENT360_LAB_ADVISOR_<COLLEGE>` sees that college's rows; the institution-wide roles see everything. Onboarding a new college = **create a role with the right name** - no policy change.

⚠️ **Gotcha - why not a mapping table?** The natural design is a `ROLE_COLLEGE_SCOPE` table the registrar owns, read by the policy through a subquery. We tried it: **any row access policy containing a subquery disables change tracking on the protected table**, which breaks everything that depends on change tracking - *dynamic tables* and *Cortex Search services* that read it. Expression-only policies (like this one) keep both working.

| Policy style | Entitlements live in | Works with dynamic tables / search services reading the table? |
|---|---|---|
| Expression + role-name convention (**used here**) | Role names | Yes |
| Mapping table + subquery | A table | **No** (no change tracking) |
| Mapping table, but policy applied only to a *serving* view that nothing incremental reads | A table | Yes, with care |

✅ **Best practice:** apply policies at the **serving layer** (what agents and BI read), keep the pipeline beneath it policy-free and owned by the pipeline role.""")
n.sql("create_scope", "Row access policy", f"""
USE ROLE {ROLE};
USE SCHEMA GOVERNANCE;

CREATE OR REPLACE ROW ACCESS POLICY GOVERNANCE.COLLEGE_SCOPE_RAP AS (COLLEGE STRING) RETURNS BOOLEAN ->
  CURRENT_ROLE() IN ('{ROLE}', 'ACCOUNTADMIN', '{IR}')                       -- institution-wide roles
  OR CURRENT_ROLE() = 'STUDENT360_LAB_ADVISOR_' || UPPER(REGEXP_REPLACE(COLLEGE, '[^A-Za-z]', ''));  -- college-scoped advisors

ALTER DYNAMIC TABLE CURATED.STUDENT_360             ADD ROW ACCESS POLICY GOVERNANCE.COLLEGE_SCOPE_RAP ON (COLLEGE);
ALTER TABLE         CURATED.ADVISING_NOTE_ENRICHED  ADD ROW ACCESS POLICY GOVERNANCE.COLLEGE_SCOPE_RAP ON (COLLEGE);
ALTER VIEW          CURATED.COURSE_ENROLLMENT       ADD ROW ACCESS POLICY GOVERNANCE.COLLEGE_SCOPE_RAP ON (COLLEGE);
SELECT 'Row access policy applied to STUDENT_360, ADVISING_NOTE_ENRICHED, COURSE_ENROLLMENT' AS STATUS;
""")

n.md("""## Step 3: Column-Level PII Masking

🛠️ Email, phone and date of birth are masked for every role except the ones with a need to contact the student. The policy is applied to the **column**, so it follows the data into every query, view, semantic view and agent answer.""")
n.sql("create_masking", "Masking policies", f"""
USE ROLE {ROLE};
USE SCHEMA GOVERNANCE;

CREATE OR REPLACE MASKING POLICY GOVERNANCE.PII_STRING_MASK AS (val STRING) RETURNS STRING ->
  CASE WHEN CURRENT_ROLE() IN ('{ROLE}', 'ACCOUNTADMIN', '{ADV}') THEN val
       ELSE '***MASKED***' END;

CREATE OR REPLACE MASKING POLICY GOVERNANCE.PII_DATE_MASK AS (val DATE) RETURNS DATE ->
  CASE WHEN CURRENT_ROLE() IN ('{ROLE}', 'ACCOUNTADMIN', '{ADV}') THEN val
       ELSE NULL END;

ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN EMAIL         SET MASKING POLICY GOVERNANCE.PII_STRING_MASK;
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN PHONE         SET MASKING POLICY GOVERNANCE.PII_STRING_MASK;
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN DATE_OF_BIRTH SET MASKING POLICY GOVERNANCE.PII_DATE_MASK;
SELECT 'Masking applied to EMAIL, PHONE, DATE_OF_BIRTH' AS STATUS;
""")

n.md("""## Step 4: Classify Columns with Tags (documentation + discoverability)

🛠️ A FERPA-style classification tag makes it obvious - to stewards, auditors and downstream tooling - which columns are directory information, which are non-directory education records, and which are sensitive.

🔹 **Tag-based masking** (attach a masking policy to the *tag*, so any column you tag is masked automatically) is the scalable next step once you have hundreds of tables. We keep direct policies here so each effect is visible.

🔹 `SYSTEM$CLASSIFY` can *propose* semantic and privacy categories for columns of an existing table - useful for a first pass on a new source.""")
n.sql("create_tags", "Classification tags", f"""
USE ROLE {ROLE};
CREATE OR REPLACE TAG GOVERNANCE.FERPA_CLASS
  ALLOWED_VALUES 'DIRECTORY', 'EDUCATION_RECORD', 'SENSITIVE'
  COMMENT = 'FERPA-style classification of student data columns';

ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN FULL_NAME     SET TAG GOVERNANCE.FERPA_CLASS = 'DIRECTORY';
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN MAJOR         SET TAG GOVERNANCE.FERPA_CLASS = 'DIRECTORY';
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN CURRENT_GPA   SET TAG GOVERNANCE.FERPA_CLASS = 'EDUCATION_RECORD';
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN UNMET_NEED    SET TAG GOVERNANCE.FERPA_CLASS = 'SENSITIVE';
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN BALANCE_DUE   SET TAG GOVERNANCE.FERPA_CLASS = 'SENSITIVE';
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN EMAIL         SET TAG GOVERNANCE.FERPA_CLASS = 'SENSITIVE';
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN PHONE         SET TAG GOVERNANCE.FERPA_CLASS = 'SENSITIVE';
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN DATE_OF_BIRTH SET TAG GOVERNANCE.FERPA_CLASS = 'SENSITIVE';
ALTER DYNAMIC TABLE CURATED.STUDENT_360 MODIFY COLUMN RETENTION_RISK_SCORE SET TAG GOVERNANCE.FERPA_CLASS = 'EDUCATION_RECORD';

SELECT COLUMN_NAME, TAG_VALUE
FROM TABLE({DB}.INFORMATION_SCHEMA.TAG_REFERENCES_ALL_COLUMNS('{DB}.CURATED.STUDENT_360', 'TABLE'))
WHERE TAG_NAME = 'FERPA_CLASS' ORDER BY TAG_VALUE, COLUMN_NAME;
""")

n.md("""## Step 5: Prove It - Test as Each Role

🛠️ Switch into each consumer role and run the **same query**. This is the most persuasive 60 seconds in the whole workshop: the data layer, not the prompt, decides what comes back.""")
n.sql("test_as_advisor", "Test as Engineering advisor", f"""
USE ROLE {ADV};
USE SECONDARY ROLES NONE;
USE WAREHOUSE {WH};
-- Expect: only Engineering rows, real emails/phones
SELECT COLLEGE, COUNT(*) AS STUDENTS_VISIBLE FROM {DB}.CURATED.STUDENT_360 GROUP BY 1;
SELECT FULL_NAME, EMAIL, PHONE, DATE_OF_BIRTH, RISK_TIER FROM {DB}.CURATED.STUDENT_360 ORDER BY RETENTION_RISK_SCORE DESC LIMIT 3;
-- The semantic view and the course view inherit the same scope:
SELECT * FROM SEMANTIC_VIEW({DB}.SEMANTIC.STUDENT_360_SV DIMENSIONS students.COLLEGE METRICS students.STUDENT_COUNT);
SELECT COLLEGE, COUNT(*) AS COURSE_ROWS_VISIBLE FROM {DB}.CURATED.COURSE_ENROLLMENT GROUP BY 1;
""")
n.sql("test_as_ir", "Test as IR analyst", f"""
USE ROLE {IR};
USE SECONDARY ROLES NONE;
USE WAREHOUSE {WH};
-- Expect: all colleges, but PII masked
SELECT COLLEGE, COUNT(*) AS STUDENTS_VISIBLE FROM {DB}.CURATED.STUDENT_360 GROUP BY 1 ORDER BY 1;
SELECT FULL_NAME, EMAIL, PHONE, DATE_OF_BIRTH, RISK_TIER FROM {DB}.CURATED.STUDENT_360 ORDER BY RETENTION_RISK_SCORE DESC LIMIT 3;
""")
n.sql("test_no_raw", "Test: RAW is unreachable", f"""
USE ROLE {ADV};
USE SECONDARY ROLES NONE;
USE WAREHOUSE {WH};
-- Expect an error: the consumer role has no privilege on the RAW schema (un-redacted notes live there)
SELECT NOTE_TEXT FROM {DB}.RAW.ADVISING_NOTE LIMIT 1;
""")

n.md("""## Step 6: The Cortex Search Owner's-Rights Gotcha (and the fix)

⚠️ **Cortex Search runs with *owner's rights*.** The row access policy you just built protects `STUDENT_360` and the notes table - but a role with `USAGE` on a **search service** can retrieve *every row that was indexed*, regardless of its own row-level entitlements. Let's prove it.

🛠️ First grant the shared notes service to the Engineering advisor (the "naive" setup) and look at what it can see.""")
n.sql("naive_grant", "Naive grant of the shared notes service", f"""
USE ROLE ACCOUNTADMIN;
GRANT USAGE ON CORTEX SEARCH SERVICE {DB}.AGENTS.ADVISING_NOTES_SEARCH TO ROLE {ADV};
USE ROLE {ADV};
USE SECONDARY ROLES NONE;
USE WAREHOUSE {WH};
-- The advisor is scoped to Engineering by the row access policy ... but the search service is not
SELECT r.value:COLLEGE::STRING AS COLLEGE_RETURNED, COUNT(*) AS HITS
FROM TABLE(FLATTEN(PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
  '{DB}.AGENTS.ADVISING_NOTES_SEARCH',
  '{{"query": "student cannot afford tuition", "columns": ["COLLEGE"], "limit": 50}}'))['results'])) r
GROUP BY 1 ORDER BY 2 DESC;
""")
n.md("""👆 **Notes from other colleges came back.** Row-level scope did not apply. The fix is architectural - scope the *index*, not just the table. Options, in order of preference:

| Option | How | Trade-off |
|---|---|---|
| **A. One search service per audience** (used here) | Source query filters to the audience (`WHERE COLLEGE = 'Engineering'`); grant only that service to that audience | Strongest isolation; a few more objects (generate them from a template) |
| **B. Restrict the shared service** to roles that may see *all* notes | Grant `USAGE` only to institution-wide roles (e.g. IR, Dean of Students) | Simple; advisors don't get free-text search |
| **C. Filter at query time** by attribute (`filter: {"@eq": {"COLLEGE": ...}}`) | Agent/tool passes a filter | **Not a security control** - the caller controls the filter. Use only as a convenience on top of A or B |

🛠️ We apply **A + B**: revoke the shared service from the advisor, create an Engineering-only service, and grant that instead.""")
n.sql("scoped_search", "Per-audience search service", f"""
USE ROLE ACCOUNTADMIN;
REVOKE USAGE ON CORTEX SEARCH SERVICE {DB}.AGENTS.ADVISING_NOTES_SEARCH FROM ROLE {ADV};
GRANT  USAGE ON CORTEX SEARCH SERVICE {DB}.AGENTS.ADVISING_NOTES_SEARCH TO ROLE {IR};   -- IR is institution-wide by design

USE ROLE {ROLE};
USE WAREHOUSE {WH};
CREATE OR REPLACE CORTEX SEARCH SERVICE {DB}.AGENTS.ADVISING_NOTES_SEARCH_ENGINEERING
  ON NOTE_TEXT_REDACTED
  ATTRIBUTES STUDENT_ID, COLLEGE, NOTE_THEME, NOTE_TYPE, ADVISOR_NAME, NOTE_DATE
  WAREHOUSE = {WH}
  TARGET_LAG = '1 hour'
  COMMENT = 'Engineering-only slice of the PII-redacted advising notes (scoped index; owner-rights safe)'
AS (
  SELECT NOTE_ID, NOTE_TEXT_REDACTED, STUDENT_ID, COLLEGE, NOTE_THEME, NOTE_TYPE, ADVISOR_NAME, NOTE_DATE
  FROM {DB}.CURATED.ADVISING_NOTE_ENRICHED
  WHERE COLLEGE = 'Engineering'
);
USE ROLE ACCOUNTADMIN;
GRANT USAGE ON CORTEX SEARCH SERVICE {DB}.AGENTS.ADVISING_NOTES_SEARCH_ENGINEERING TO ROLE {ADV};
SELECT 'Engineering advisor now has only the Engineering-scoped notes index' AS STATUS;
""")
n.sql("verify_scoped_search", "Verify scoped search", f"""
USE ROLE {ADV};
USE SECONDARY ROLES NONE;
USE WAREHOUSE {WH};
SELECT r.value:COLLEGE::STRING AS COLLEGE_RETURNED, COUNT(*) AS HITS
FROM TABLE(FLATTEN(PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
  '{DB}.AGENTS.ADVISING_NOTES_SEARCH_ENGINEERING',
  '{{"query": "student cannot afford tuition", "columns": ["COLLEGE"], "limit": 50}}'))['results'])) r
GROUP BY 1;
-- And the shared service is now refused:
-- SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW('{DB}.AGENTS.ADVISING_NOTES_SEARCH', '{{"query":"x","limit":1}}');   -- expect: insufficient privileges
""")

n.sql("reset_role", "Back to lab admin", f"""
USE ROLE {ROLE};
USE WAREHOUSE {WH};
SELECT CURRENT_ROLE() AS BACK_TO;
""")

n.md("""## 🧠 Governance Checklist for Higher-Ed AI

| Control | Where | Status |
|---|---|---|
| Least-privilege roles, no grants on `RAW` | Step 1 | ✅ |
| Row-level scope by college (expression policy, change-tracking safe) | Step 2 | ✅ |
| PII masked at the column, follows every consumer | Step 3 | ✅ |
| Columns classified (FERPA-style tags) | Step 4 | ✅ |
| PII removed from free text *before* indexing | Notebook 01 (`AI_REDACT`) | ✅ |
| Search indexes scoped per audience | Step 6 | ✅ |
| Rejection rules for contact-detail / adverse-action questions | Notebook 02 (`AI_QUESTION_CATEGORIZATION`) | ✅ |
| Audit: who asked what, what did it cost | Notebook 05 | next |
| SSO/SCIM, MFA, network policy, PrivateLink | Customer account | reference |
| Guardrails (`AI_SETTINGS`) enabled | Account-level (Enterprise Edition) | reference |

> 🎓 **The conversation to have with your registrar and CISO:** *"the agent has no memory of who it is allowed to tell what. The database does."*""")

n.footer([
    f"Roles `{ADV}` and `{IR}` with layers 1, 3 and 4 of the access model",
    "Row access policy (role-name convention) on the Student 360, notes and course view",
    "Masking policies on EMAIL, PHONE, DATE_OF_BIRTH; FERPA classification tags",
    "A scoped `ADVISING_NOTES_SEARCH_ENGINEERING` index, after proving the owner's-rights gap",
],
    [
        "Enforce access on the **data**, not in the prompt - policies follow the data into every agent answer.",
        "Subquery-based row policies disable change tracking and break dynamic tables / search services - use expression policies, or policy only the serving layer.",
        "Cortex Search is owner's-rights: scope the *index* per audience; query-time filters are conveniences, not controls.",
        "Test every consumer role with the same query before you build the agent.",
    ],
    "**Notebook 04** - build and harden the agent that sits on top of all of this.")
n.write()
