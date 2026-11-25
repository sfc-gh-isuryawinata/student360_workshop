from lib import NB, DB, ROLE, WH

n = NB("Notebook_02_Context_Layer.ipynb", 2, "Context Layer for AI", "Phase 2 - Give the data meaning", 35)
n.header([
    "🛠️ Creates a **serving view** of course enrollments that inherits the Student 360's governance",
    "🛠️ Builds two **Cortex Search services**: fuzzy student-name matching, and semantic (RAG) search over the redacted advising notes",
    "🛠️ Authors a governed **semantic view** - descriptions, synonyms, metrics, verified queries and custom instructions - as the single source of truth for structured questions",
    "🛠️ **Validates the semantic view directly** before any agent exists",
],
    "A table is not an answer. An LLM does not know that *HIGH* risk means a score of 60+, that *DFW* means D/F/Withdraw, or that *Pell* is a federal grant. The context layer is where you write that down **once**, so every agent and every user gets the same answer.",
    "Notebook 01")

n.sql("set_context", "Set Context", f"""
USE ROLE {ROLE};
USE DATABASE {DB};
USE SCHEMA SEMANTIC;
USE WAREHOUSE {WH};
SELECT CURRENT_ROLE(), CURRENT_SCHEMA();
""")

n.md("""## Step 1: A Course-Level Serving View

🛠️ The semantic view will have **three logical tables** (students, courses, advising notes). Course rows come from the SIS, but we join to `STUDENT_360` so that the view only contains **students the Student 360 covers** - and, as you will see in Notebook 03, it **inherits that table's row-level security automatically**.

🔹 `DFW_FLAG` encodes the registrar's definition once: a course counts as DFW if the final grade is **D, F or W**, or - for the in-progress term - the midterm grade is **D or F**.""")
n.sql("create_course_view", "Course enrollment view", """
CREATE OR REPLACE VIEW CURATED.COURSE_ENROLLMENT
  COMMENT = 'Course enrollments for students in the Student 360 (inherits its row-level security). DFW = final grade D/F/W, or midterm D/F in the current term.'
AS
SELECT
  e.ENROLLMENT_ID, e.STUDENT_ID, s.COLLEGE, e.TERM, e.COURSE_CODE, e.COURSE_TITLE, e.DEPARTMENT, e.CREDITS,
  e.FINAL_GRADE, e.MIDTERM_GRADE, e.GRADE_POINTS, e.ENROLLMENT_STATUS AS COURSE_STATUS,
  IFF(COALESCE(e.FINAL_GRADE, e.MIDTERM_GRADE) IN ('D','F','W'), 1, 0) AS DFW_FLAG
FROM RAW.SIS_ENROLLMENT e
JOIN CURATED.STUDENT_360 s ON s.STUDENT_ID = e.STUDENT_ID;
SELECT TERM, COUNT(*) AS ROWS_, ROUND(100 * AVG(DFW_FLAG), 1) AS DFW_PCT FROM CURATED.COURSE_ENROLLMENT GROUP BY 1 ORDER BY 1;
""")

n.md("""## Step 2: Cortex Search Service #1 - Fuzzy Student-Name Matching

🛠️ Advisors type *"Maria Garcia"*, *"maria garcia"* or *"Marai Garcia"*; the stored value is exactly `Maria Garcia`. Cortex Analyst must put the **exact literal** in its `WHERE` clause. A search service over the distinct values of `FULL_NAME` resolves the fuzzy reference. Step 4 links it to the dimension.

🔹 **When to use this pattern:** high-cardinality *identifier* columns (names, course titles, program names). **Not** for low-cardinality columns (college, risk tier) - list those values in the dimension description instead.""")
n.sql("create_name_search", "Student-name search service", f"""
CREATE OR REPLACE CORTEX SEARCH SERVICE AGENTS.STUDENT_NAME_SEARCH
  ON FULL_NAME
  WAREHOUSE = {WH}
  TARGET_LAG = '1 hour'
  COMMENT = 'Fuzzy literal matching for student names, linked to the STUDENT_360_SV FULL_NAME dimension'
AS (SELECT DISTINCT FULL_NAME FROM CURATED.STUDENT_360);
SHOW CORTEX SEARCH SERVICES IN SCHEMA AGENTS;
""")

n.md("""## Step 3: Cortex Search Service #2 - Advising Notes (RAG)

🛠️ A **different** kind of search. Step 2 indexes a *short identifier* for literal matching. This indexes *document bodies* for semantic retrieval, so the agent can answer qualitative questions - *"What are advisors hearing from students who are thinking of leaving?"* - that no SQL could.

✅ **Best practice - index only what the agent may see.** We index `NOTE_TEXT_REDACTED` (the `AI_REDACT`ed text from Notebook 01). The raw note is not in this service and the agent's role has no grant on `RAW`.

⚠️ **Governance gotcha:** Cortex Search runs with **owner's rights**. Any role granted `USAGE` on the service can retrieve *every indexed row*, regardless of the role's row access policies on the source table. Notebook 03 shows the mitigation (scope with attributes / separate services per audience, and only grant to roles allowed to see all notes).""")
n.sql("create_notes_search", "Advising-notes search service", f"""
CREATE OR REPLACE CORTEX SEARCH SERVICE AGENTS.ADVISING_NOTES_SEARCH
  ON NOTE_TEXT_REDACTED
  ATTRIBUTES STUDENT_ID, COLLEGE, NOTE_THEME, NOTE_TYPE, ADVISOR_NAME, NOTE_DATE
  WAREHOUSE = {WH}
  TARGET_LAG = '1 hour'
  COMMENT = 'Semantic search over PII-redacted advising notes (Fall 2026)'
AS (
  SELECT NOTE_ID, NOTE_TEXT_REDACTED, STUDENT_ID, COLLEGE, NOTE_THEME, NOTE_TYPE, ADVISOR_NAME, NOTE_DATE
  FROM CURATED.ADVISING_NOTE_ENRICHED
);
SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
  '{DB}.AGENTS.ADVISING_NOTES_SEARCH',
  '{{"query": "student cannot afford tuition and may stop out", "columns": ["NOTE_TEXT_REDACTED","NOTE_THEME","COLLEGE"], "limit": 3}}'
)):results AS TOP_3_NOTES;
""")

n.md("""## Step 4: Create the Semantic View

🛠️ This defines meaning on top of the curated tables:

- **Logical tables:** `students`, `courses`, `notes` joined on `STUDENT_ID`
- **Facts / dimensions / metrics** with business-language comments and synonyms
- **Custom instructions** (two distinct kinds - see below) and **verified queries**
- The `FULL_NAME` dimension is wired to the fuzzy-match search service from Step 2

✅ **What we deliberately left out:** `EMAIL`, `PHONE` and `DATE_OF_BIRTH`. The cheapest way to stop an agent leaking a column is to not expose it. Least exposure first, masking policies second (Notebook 03).""")
n.sql("create_semantic_view", "Create semantic view", f"""
CREATE OR REPLACE SEMANTIC VIEW {DB}.SEMANTIC.STUDENT_360_SV

  TABLES (
    students AS {DB}.CURATED.STUDENT_360
      PRIMARY KEY (STUDENT_ID)
      WITH SYNONYMS = ('student', 'student 360', 'learner')
      COMMENT = 'One row per ACTIVE student at Lakeside University, unifying SIS, LMS, Financial Aid, Bursar, Advising CRM and Campus Card data, with an explainable retention-risk score. Snapshot as of week 10 of Fall 2026.',
    courses AS {DB}.CURATED.COURSE_ENROLLMENT
      PRIMARY KEY (ENROLLMENT_ID)
      WITH SYNONYMS = ('course enrollment', 'class', 'section')
      COMMENT = 'One row per student per course per term (Fall 2025, Spring 2026, Fall 2026). Fall 2026 is in progress: it has MIDTERM_GRADE but no FINAL_GRADE.',
    notes AS {DB}.CURATED.ADVISING_NOTE_ENRICHED
      PRIMARY KEY (NOTE_ID)
      WITH SYNONYMS = ('advising note', 'advisor note')
      COMMENT = 'One row per advising note from the Advising CRM. Text is PII-redacted. Each note is tagged with an AI-classified theme.'
  )

  RELATIONSHIPS (
    courses_to_students AS courses(STUDENT_ID) REFERENCES students,
    notes_to_students   AS notes(STUDENT_ID)   REFERENCES students
  )

  FACTS (
    students.CURRENT_GPA AS CURRENT_GPA
      COMMENT = 'Current grade point average on a 4.0 scale. Cumulative GPA for continuing students; midterm GPA for first-term freshmen.',
    students.RETENTION_RISK_SCORE AS RETENTION_RISK_SCORE
      COMMENT = 'Retention-risk score from 0 (no risk signals) to 100 (maximum). A triage signal to prioritise outreach, not a prediction about an individual.',
    students.UNMET_NEED AS UNMET_NEED
      COMMENT = 'Financial need in USD not covered by grants, scholarships or loans for 2026-27. Null if the student has no financial aid record.',
    students.BALANCE_DUE AS BALANCE_DUE
      COMMENT = 'Current outstanding Bursar balance in USD.',
    students.LOGIN_TREND_PCT AS LOGIN_TREND_PCT
      COMMENT = 'Change in average weekly LMS logins between weeks 1-3 and weeks 8-10. -0.5 means logins fell by half.',
    students.ASSIGNMENT_SUBMISSION_RATE AS ASSIGNMENT_SUBMISSION_RATE
      COMMENT = 'Share of LMS assignments due that were submitted this term (0 to 1).',
    students.CAMPUS_TOUCHPOINTS_PER_WEEK AS CAMPUS_TOUCHPOINTS_PER_WEEK
      COMMENT = 'Average weekly library visits + rec-center visits + events attended from campus ID-card swipes.',
    students.DAYS_SINCE_ADVISING AS DAYS_SINCE_ADVISING
      COMMENT = 'Days since the most recent advising note, as of 2 Nov 2026. 999 means no advising note on file.',
    students.CREDITS_EARNED AS CREDITS_EARNED
      COMMENT = 'Credit hours earned before the current term.',
    courses.CREDITS AS CREDITS
      COMMENT = 'Credit hours for the course.',
    courses.GRADE_POINTS AS GRADE_POINTS
      COMMENT = 'Grade points on a 4.0 scale (final grade; midterm grade for in-progress courses). Null for withdrawals.',
    courses.DFW_FLAG AS DFW_FLAG
      COMMENT = '1 if the course is a DFW: final grade D, F or W (or midterm D/F for in-progress courses); otherwise 0.'
  )

  DIMENSIONS (
    students.STUDENT_ID AS STUDENT_ID
      COMMENT = 'Unique student identifier from the Student Information System (format S0000123).',
    students.FULL_NAME AS FULL_NAME
      WITH SYNONYMS = ('student name', 'name')
      COMMENT = 'Student full name (first and last).'
      WITH CORTEX SEARCH SERVICE {DB}.AGENTS.STUDENT_NAME_SEARCH,
    students.COLLEGE AS COLLEGE
      WITH SYNONYMS = ('school', 'division')
      COMMENT = 'Academic college. Values: Engineering, Arts & Sciences, Business, Nursing & Health, Education.',
    students.MAJOR AS MAJOR
      WITH SYNONYMS = ('program', 'degree program')
      COMMENT = 'Declared major (for example Computer Science, Nursing, Accounting, Biology).',
    students.CLASS_LEVEL AS CLASS_LEVEL
      WITH SYNONYMS = ('year', 'class standing')
      COMMENT = 'Class standing: Freshman, Sophomore, Junior or Senior.',
    students.ADMIT_TERM AS ADMIT_TERM
      WITH SYNONYMS = ('cohort', 'entry term')
      COMMENT = 'Term the student was first admitted (their cohort), for example Fall 2024.',
    students.FIRST_GEN_FLAG AS FIRST_GEN_FLAG
      WITH SYNONYMS = ('first generation', 'first-gen')
      COMMENT = 'Y if the student is first-generation (first in family to attend college), otherwise N.',
    students.RESIDENCY AS RESIDENCY
      COMMENT = 'Residency classification: In-State, Out-of-State or International.',
    students.ASSIGNED_ADVISOR AS ASSIGNED_ADVISOR
      WITH SYNONYMS = ('advisor', 'academic advisor')
      COMMENT = 'Name of the student''s assigned academic advisor.',
    students.RISK_TIER AS RISK_TIER
      WITH SYNONYMS = ('risk level', 'at-risk status', 'retention risk')
      COMMENT = 'Retention-risk band derived from RETENTION_RISK_SCORE: HIGH (60 or more), MEDIUM (30 to 59), LOW (below 30).',
    students.TOP_RISK_DRIVERS AS TOP_RISK_DRIVERS
      WITH SYNONYMS = ('why at risk', 'risk factors', 'risk reasons')
      COMMENT = 'Semicolon-separated list of the rules that raised the risk score (for example Low GPA; Unmet financial need; Account hold).',
    students.HOLD_TYPE AS HOLD_TYPE
      WITH SYNONYMS = ('account hold', 'bursar hold')
      COMMENT = 'Bursar hold: NONE, FINANCIAL_HOLD or REGISTRATION_HOLD (blocks course registration).',
    students.SAP_STATUS AS SAP_STATUS
      WITH SYNONYMS = ('satisfactory academic progress')
      COMMENT = 'Financial-aid Satisfactory Academic Progress: MEETING, WARNING or SUSPENDED. Null if no aid record.',
    students.PELL_ELIGIBLE AS PELL_ELIGIBLE
      WITH SYNONYMS = ('pell grant', 'pell')
      COMMENT = 'Y if eligible for a federal Pell Grant (low-income indicator), otherwise N.',
    students.LATEST_CONCERN_THEME AS LATEST_CONCERN_THEME
      COMMENT = 'Theme of the student''s most recent concern-flagged advising note (financial hardship, mental health and wellbeing, academic struggle, considering leaving). Null if no concerns.',
    courses.TERM AS TERM
      COMMENT = 'Academic term: Fall 2025, Spring 2026 or Fall 2026 (current, in progress).',
    courses.COURSE_CODE AS COURSE_CODE
      COMMENT = 'Course code such as MATH101 or CHEM101.',
    courses.COURSE_TITLE AS COURSE_TITLE
      COMMENT = 'Course title such as Calculus I or General Chemistry.',
    courses.DEPARTMENT AS DEPARTMENT
      COMMENT = 'Academic department that owns the course.',
    courses.FINAL_GRADE AS FINAL_GRADE
      COMMENT = 'Final letter grade (A, B+, B, B-, C, D, F) or W for withdrawal. Null while the course is in progress.',
    courses.MIDTERM_GRADE AS MIDTERM_GRADE
      COMMENT = 'Midterm letter grade. Populated only for the in-progress Fall 2026 term.',
    courses.COURSE_STATUS AS COURSE_STATUS
      COMMENT = 'ENROLLED (in progress), COMPLETED or WITHDRAWN.',
    notes.NOTE_DATE AS NOTE_DATE
      COMMENT = 'Date the advising note was written.',
    notes.NOTE_TYPE AS NOTE_TYPE
      COMMENT = 'Advisor-selected category: Financial, Wellbeing, Academic, Retention, Career or Planning.',
    notes.NOTE_THEME AS NOTE_THEME
      COMMENT = 'AI-classified theme: financial hardship, mental health and wellbeing, academic struggle, considering leaving, or on track.',
    notes.ADVISOR_NAME AS ADVISOR_NAME
      COMMENT = 'Advisor who wrote the note.'
  )

  METRICS (
    students.STUDENT_COUNT AS COUNT(DISTINCT students.STUDENT_ID)
      WITH SYNONYMS = ('number of students', 'headcount', 'enrollment')
      COMMENT = 'Number of distinct active students.',
    students.AVG_GPA AS AVG(students.CURRENT_GPA)
      WITH SYNONYMS = ('average gpa', 'mean gpa')
      COMMENT = 'Average current GPA on a 4.0 scale.',
    students.AVG_RISK_SCORE AS AVG(students.RETENTION_RISK_SCORE)
      COMMENT = 'Average retention-risk score (0-100).',
    students.HIGH_RISK_STUDENT_COUNT AS COUNT(DISTINCT CASE WHEN students.RISK_TIER = 'HIGH' THEN students.STUDENT_ID END)
      WITH SYNONYMS = ('at-risk students', 'high risk students')
      COMMENT = 'Number of students in the HIGH retention-risk tier.',
    students.HIGH_RISK_PCT AS 100.0 * COUNT(DISTINCT CASE WHEN students.RISK_TIER = 'HIGH' THEN students.STUDENT_ID END) / NULLIF(COUNT(DISTINCT students.STUDENT_ID), 0)
      WITH SYNONYMS = ('at-risk rate', 'percent at risk')
      COMMENT = 'Percentage of students in the HIGH retention-risk tier.',
    students.TOTAL_UNMET_NEED AS SUM(students.UNMET_NEED)
      COMMENT = 'Total unmet financial need in USD across students.',
    students.TOTAL_BALANCE_DUE AS SUM(students.BALANCE_DUE)
      COMMENT = 'Total outstanding Bursar balance in USD.',
    students.STUDENTS_WITH_HOLDS AS COUNT(DISTINCT CASE WHEN students.HOLD_TYPE <> 'NONE' THEN students.STUDENT_ID END)
      COMMENT = 'Number of students with any Bursar hold.',
    students.AVG_LOGIN_TREND AS AVG(students.LOGIN_TREND_PCT)
      COMMENT = 'Average change in weekly LMS logins (early vs. recent weeks).',
    students.AVG_SUBMISSION_RATE AS AVG(students.ASSIGNMENT_SUBMISSION_RATE)
      COMMENT = 'Average LMS assignment submission rate (0-1).',
    courses.ENROLLMENT_COUNT AS COUNT(DISTINCT courses.ENROLLMENT_ID)
      COMMENT = 'Number of student-course enrollment records.',
    courses.DFW_COUNT AS SUM(courses.DFW_FLAG)
      COMMENT = 'Number of DFW course enrollments (D, F or W).',
    courses.DFW_RATE_PCT AS 100.0 * SUM(courses.DFW_FLAG) / NULLIF(COUNT(DISTINCT courses.ENROLLMENT_ID), 0)
      WITH SYNONYMS = ('dfw rate', 'failure rate', 'withdrawal rate')
      COMMENT = 'Percentage of course enrollments that are D, F or W.',
    notes.NOTE_COUNT AS COUNT(DISTINCT notes.NOTE_ID)
      COMMENT = 'Number of advising notes.',
    notes.CONCERN_NOTE_COUNT AS COUNT(DISTINCT CASE WHEN notes.CONCERN_FLAG THEN notes.NOTE_ID END)
      COMMENT = 'Number of advising notes whose AI-classified theme is a concern (anything other than on track).'
  )

  COMMENT = 'Lakeside University Student 360 - retention, academics, engagement, finances and advising for active students (Fall 2026, week 10).'

  AI_SQL_GENERATION '
    -- Business rules for SQL generation:
    -- 1. "At-risk" or "high risk" students means RISK_TIER = ''HIGH''. Unless asked otherwise rank by RETENTION_RISK_SCORE descending.
    -- 2. "Current term" means Fall 2026. Fall 2026 is in progress: use MIDTERM_GRADE, never FINAL_GRADE, for that term.
    -- 3. DFW rate = share of enrollments with a final grade D, F or W (or midterm D/F in progress). Use the DFW_RATE_PCT metric.
    -- 4. Always show STUDENT_ID next to FULL_NAME so duplicates and follow-ups are unambiguous.
    -- 5. When asked about an advisor''s caseload, filter on ASSIGNED_ADVISOR and order by RETENTION_RISK_SCORE descending.
    -- 6. Percentages are 0-100 (already multiplied). Round GPA to 2 decimals, money to whole dollars.
    -- 7. NULL UNMET_NEED means no financial-aid record; do not treat it as zero need.
    -- 8. Do not select or infer EMAIL, PHONE or DATE_OF_BIRTH. They are intentionally not in this model.
  '

  AI_QUESTION_CATEGORIZATION '
    -- Reject and explain:
    -- * Questions asking for contact details (email, phone, home address) or date of birth, or social security numbers: reply that contact details are not available through this assistant and to use the advising system of record.
    -- * Questions asking to rank or label individual students by race, ethnicity, religion, disability or immigration status.
    -- * Questions asking to decide admission, dismissal, aid revocation or other adverse action for a named student.
    -- Ask a clarifying question when:
    -- * A student name is ambiguous or matches more than one student: ask which STUDENT_ID.
    -- * The user says "last year" or "this year" without a term.
  '

  AI_VERIFIED_QUERIES (
    high_risk_by_college AS (
      QUESTION 'How many high-risk students do we have in each college?'
      SQL 'SELECT COLLEGE, COUNT(*) AS HIGH_RISK_STUDENTS, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS PCT_OF_HIGH_RISK
           FROM {DB}.CURATED.STUDENT_360 WHERE RISK_TIER = ''HIGH'' GROUP BY COLLEGE ORDER BY HIGH_RISK_STUDENTS DESC'
    ),
    top_risk_students AS (
      QUESTION 'Who are the 10 students we should reach out to first and why?'
      SQL 'SELECT STUDENT_ID, FULL_NAME, COLLEGE, MAJOR, RETENTION_RISK_SCORE, TOP_RISK_DRIVERS, ASSIGNED_ADVISOR
           FROM {DB}.CURATED.STUDENT_360 WHERE RISK_TIER = ''HIGH'' ORDER BY RETENTION_RISK_SCORE DESC, DAYS_SINCE_ADVISING DESC LIMIT 10'
    ),
    advisor_caseload_risk AS (
      QUESTION 'Show each advisor''s caseload size and how many of their students are high risk'
      SQL 'SELECT ASSIGNED_ADVISOR, COUNT(*) AS CASELOAD, COUNT_IF(RISK_TIER = ''HIGH'') AS HIGH_RISK, ROUND(AVG(RETENTION_RISK_SCORE), 1) AS AVG_RISK_SCORE
           FROM {DB}.CURATED.STUDENT_360 GROUP BY ASSIGNED_ADVISOR ORDER BY HIGH_RISK DESC'
    ),
    highest_dfw_courses AS (
      QUESTION 'Which courses have the highest DFW rate?'
      SQL 'SELECT COURSE_CODE, COURSE_TITLE, COUNT(*) AS ENROLLMENTS, ROUND(100.0 * SUM(DFW_FLAG) / COUNT(*), 1) AS DFW_RATE_PCT
           FROM {DB}.CURATED.COURSE_ENROLLMENT GROUP BY COURSE_CODE, COURSE_TITLE HAVING COUNT(*) >= 50 ORDER BY DFW_RATE_PCT DESC LIMIT 10'
    ),
    holds_and_risk AS (
      QUESTION 'Which students have a registration hold and are also high risk?'
      SQL 'SELECT STUDENT_ID, FULL_NAME, COLLEGE, BALANCE_DUE, DAYS_PAST_DUE, RETENTION_RISK_SCORE
           FROM {DB}.CURATED.STUDENT_360 WHERE HOLD_TYPE = ''REGISTRATION_HOLD'' AND RISK_TIER = ''HIGH'' ORDER BY BALANCE_DUE DESC'
    ),
    first_gen_vs_not AS (
      QUESTION 'Compare first-generation and continuing-generation students on GPA and risk'
      SQL 'SELECT FIRST_GEN_FLAG, COUNT(*) AS STUDENTS, ROUND(AVG(CURRENT_GPA), 2) AS AVG_GPA, ROUND(AVG(RETENTION_RISK_SCORE), 1) AS AVG_RISK_SCORE,
                  ROUND(100.0 * COUNT_IF(RISK_TIER = ''HIGH'') / COUNT(*), 1) AS HIGH_RISK_PCT
           FROM {DB}.CURATED.STUDENT_360 GROUP BY FIRST_GEN_FLAG'
    ),
    disengaged_not_advised AS (
      QUESTION 'Which students are disengaging in the LMS but have not seen an advisor in over 45 days?'
      SQL 'SELECT STUDENT_ID, FULL_NAME, COLLEGE, LOGIN_TREND_PCT, ASSIGNMENT_SUBMISSION_RATE, DAYS_SINCE_ADVISING, ASSIGNED_ADVISOR
           FROM {DB}.CURATED.STUDENT_360 WHERE LOGIN_TREND_PCT <= -0.4 AND DAYS_SINCE_ADVISING > 45 ORDER BY LOGIN_TREND_PCT ASC LIMIT 25'
    )
  );
SELECT 'Semantic view STUDENT_360_SV created' AS STATUS;
""")

n.md("""### 🔹 Two Ways to Build: SQL vs. the UI

We authored the semantic view in **SQL** - full control and version-controllable. You can build the same thing in Snowsight:

| Object | UI path | What it gives you |
|---|---|---|
| Semantic view | AI & ML -> Cortex Analyst -> **Create with Autopilot** | Proposes dimensions, metrics and relationships from your tables and query history |
| Search service | AI & ML -> Cortex Search -> **Create** | Guided setup of source query, search column, attributes and lag |

✅ **Pragmatic pattern:** let Autopilot draft it, then export to YAML/DDL, review every description by hand, and put the DDL in Git.

### ✅ Best Practices: What Makes a Semantic View Accurate

| Rule | Where you can see it in the view above |
|---|---|
| **Descriptions are the #1 input.** Spell out abbreviations and business definitions | `DFW`, `SAP_STATUS`, `PELL_ELIGIBLE`, `RISK_TIER` thresholds all explained |
| **Synonyms** for how people actually talk | *at-risk students*, *school*, *cohort*, *pell* |
| **Metrics own the math** - define the formula once | `DFW_RATE_PCT`, `HIGH_RISK_PCT` |
| **Verified queries** teach the correct pattern for frequent questions | 7 queries above; target 10-20 in production, sourced from real advisor questions |
| **Least exposure** - leave sensitive columns out | no `EMAIL`, `PHONE`, `DATE_OF_BIRTH` |
| **Fuzzy literal matching** for identifier columns | `FULL_NAME` -> `STUDENT_NAME_SEARCH` |

### ✅ Best Practices: Custom Instructions (two distinct types)

The most common mistake is mixing the two:

| Type | Applies to | Use for | In our view |
|---|---|---|---|
| **`AI_SQL_GENERATION`** | Every generated query | Business logic, defaults, fiscal/academic-calendar definitions, data quirks | "Current term = Fall 2026", "NULL unmet need is not zero" |
| **`AI_QUESTION_CATEGORIZATION`** | How the question is understood | When to **reject** or **ask for clarification** | Reject contact-detail and adverse-action questions; clarify ambiguous names |

### 📐 Design Note: One Semantic View vs. Many

A single Cortex Analyst call works against **one** semantic view - it cannot JOIN across two. In this lab, students, courses and notes are tightly related (all join on `STUDENT_ID`), so **one view** is right.

| Situation | Recommendation |
|---|---|
| Tables join naturally around one entity and answer one family of questions | **One view** (this lab) |
| Different audiences / different grain / different owners (e.g. admissions funnel vs. student success) | **Separate views**, one agent tool each - the agent calls them sequentially and synthesises |
| Cross-domain reasoning with shared vocabulary (e.g. *student*, *course*, *program* meaning the same across Admissions, Registrar, Advancement) | Look at **ontology / knowledge-graph** approaches on top of several semantic views |

> 🧠 **Going deeper - Ontology on Snowflake.** When customers say *"our AI gives different answers depending on which dashboard it learned from"*, the fix is a shared business vocabulary across domains, not a bigger semantic view. A university has this problem acutely - *"student"* means something different to Admissions (applicant), the Registrar (enrolled) and Advancement (alumni).""")

n.md("""## Step 5: Validate - the Pre-Agent Gate

📌 **Test the semantic view directly with `SEMANTIC_VIEW()` before building the agent.** If the view returns wrong numbers, the agent will too - catch it here, in front of an SQL editor, not in front of an advisor.

Reconcile every result against the table you know is right.""")
n.sql("test_sv_college", "Test: risk by college", """
SELECT * FROM SEMANTIC_VIEW(
  STUDENT360_LAB.SEMANTIC.STUDENT_360_SV
  DIMENSIONS students.COLLEGE
  METRICS students.STUDENT_COUNT, students.HIGH_RISK_STUDENT_COUNT, students.HIGH_RISK_PCT, students.AVG_GPA
)
ORDER BY HIGH_RISK_PCT DESC;
""")
n.sql("test_sv_dfw", "Test: DFW by course", """
SELECT * FROM SEMANTIC_VIEW(
  STUDENT360_LAB.SEMANTIC.STUDENT_360_SV
  DIMENSIONS courses.COURSE_CODE, courses.COURSE_TITLE
  METRICS courses.ENROLLMENT_COUNT, courses.DFW_RATE_PCT
)
ORDER BY DFW_RATE_PCT DESC LIMIT 5;
""")
n.sql("test_sv_reconcile", "Reconcile to source", """
-- Same question answered straight from the table: the numbers must match the semantic-view result above.
SELECT COLLEGE, COUNT(*) AS STUDENT_COUNT, COUNT_IF(RISK_TIER = 'HIGH') AS HIGH_RISK_STUDENT_COUNT,
       ROUND(100.0 * COUNT_IF(RISK_TIER = 'HIGH') / COUNT(*), 2) AS HIGH_RISK_PCT, ROUND(AVG(CURRENT_GPA), 2) AS AVG_GPA
FROM STUDENT360_LAB.CURATED.STUDENT_360 GROUP BY COLLEGE ORDER BY HIGH_RISK_PCT DESC;
""")
n.sql("test_sv_cross", "Test: cross-table question", """
-- Cross-table: which advisor-noted themes show up among HIGH-risk students, by college?
SELECT * FROM SEMANTIC_VIEW(
  STUDENT360_LAB.SEMANTIC.STUDENT_360_SV
  DIMENSIONS students.COLLEGE, notes.NOTE_THEME
  METRICS notes.NOTE_COUNT
  WHERE students.RISK_TIER = 'HIGH'
)
ORDER BY COLLEGE, NOTE_COUNT DESC;
""")

n.md("""### 🛠️ Ask it in plain English (optional)

If you have access to Cortex Analyst in Snowsight, open **AI & ML -> Cortex Analyst**, choose `STUDENT360_LAB.SEMANTIC.STUDENT_360_SV` and try:
1. *Who are the 10 students we should reach out to first and why?* (matches a verified query)
2. *Which courses have the highest DFW rate in the current term?*
3. *What is the email address of Maria Garcia?* (should be **rejected** by `AI_QUESTION_CATEGORIZATION`)

## 🧠 Common Pitfalls & Production Checklist

| Pitfall | Fix |
|---|---|
| **Undefined scope** ("just one more table") | Write success criteria and boundaries first. This lab: *retention triage for advisors* |
| **Starting too big** (the whole data warehouse) | Start with **5-10 tables**, one domain, one use case |
| **Skipping verified queries** | Add **10-20** drawn from real advisor questions; keep adding from agent traces (Notebook 06) |
| **Wrong first use case** (high-stakes, ~100% accuracy bar, e.g. financial-aid eligibility rulings) | Begin with **triage and exploration** where a human always makes the decision |
| **PII in the model** | Leave it out; mask it anyway (Notebook 03) |
| **Metrics defined in prompts** | Define them in the view so SQL and every consumer agree |
| **No owner** | Assign a data steward for descriptions; review monthly |""")

n.footer([
    "`CURATED.COURSE_ENROLLMENT` serving view (DFW logic defined once)",
    "Cortex Search `STUDENT_NAME_SEARCH` - fuzzy literal matching for student names",
    "Cortex Search `ADVISING_NOTES_SEARCH` - RAG over PII-redacted notes",
    "Semantic view `STUDENT_360_SV` - descriptions, synonyms, metrics, custom instructions, 7 verified queries; validated against source",
],
    [
        "The semantic view is the single source of truth for structured questions - write definitions once, in business language.",
        "Two kinds of search: literal matching for identifiers, semantic retrieval for documents.",
        "Least exposure: leave PII out of the model; reject out-of-bounds questions with `AI_QUESTION_CATEGORIZATION`.",
        "Always validate with `SEMANTIC_VIEW()` and reconcile to the source before building the agent.",
    ],
    "**Notebook 03** - govern access: roles, row-level scope by college, PII masking - FERPA-style controls that follow the agent.")
n.write()
