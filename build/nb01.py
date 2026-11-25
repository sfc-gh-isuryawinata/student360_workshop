from lib import NB, DB, ROLE, WH

n = NB("Notebook_01_Build_Student360.ipynb", 1, "Build the Student 360", "Phase 1 - Unify the data", 40)
n.header([
    "🛠️ **Resolves student identity** across six sources into one crosswalk (exact + fuzzy match, with a measurable match rate)",
    "🛠️ Engineers per-source **feature tables** as **dynamic tables** (declarative, incremental, always fresh)",
    "🛠️ Enriches the **unstructured advising notes** with `AI_REDACT` (PII removal) and `AI_CLASSIFY` (theme)",
    "🛠️ Assembles the **`STUDENT_360`** table - one governed row per student with an explainable retention-risk score and the top risk drivers",
],
    "This is the heart of the workshop. Everything the agent says later is only as good as this table, so we build it as a **declarative pipeline** that refreshes itself, with data quality measured at each step.",
    "Notebook 00")

n.sql("set_context", "Set Context", f"""
USE ROLE {ROLE};
USE DATABASE {DB};
USE SCHEMA CURATED;
USE WAREHOUSE {WH};
SELECT CURRENT_ROLE(), CURRENT_SCHEMA();
""")

n.md("""## Step 1: Identity Resolution - the Student Crosswalk

🛠️ The SIS `STUDENT_ID` is our **golden key**. For every other system we derive a deterministic link to it:

| Source | Matching rule | Method label |
|---|---|---|
| LMS | `LOWER(email)` equals SIS email | `EMAIL_EXACT` |
| LMS (fallback) | local part before `@` equals (catches the legacy `@lakeside.com` domain) | `EMAIL_LOCALPART` |
| Financial Aid | bare number inside the SIS id | `NUMERIC_ID` |
| Advising CRM | `'STU-' + digits` | `PREFIXED_ID` |
| Campus card | roster email equals SIS email | `EMAIL_EXACT` |
| Bursar | already the SIS id | `DIRECT` |

✅ **Best practice - deterministic first, probabilistic last.** Start with exact and rule-based matches you can explain to a registrar; only reach for fuzzy/ML matching on the residue. Always keep the *method* column so every link is auditable.

🔹 The crosswalk is a **regular table, not a dynamic table**, on purpose: identity resolution is a many-way outer join that changes rarely, and you want a human to review it (match report below) before it flows downstream. In production, rebuild it with a scheduled **task** or a `MERGE`. Everything *after* the crosswalk is declarative dynamic tables.""")
n.sql("create_xwalk", "Create ID crosswalk", """
CREATE OR REPLACE TABLE CURATED.STUDENT_XWALK
  COMMENT = 'Golden-key crosswalk: SIS STUDENT_ID to every other system key, with match method'
AS
WITH lms AS (SELECT DISTINCT LOWER(LMS_USER_EMAIL) AS lms_email FROM RAW.LMS_ACTIVITY)
SELECT
  s.STUDENT_ID,
  COALESCE(l1.lms_email, l2.lms_email)                        AS LMS_EMAIL,
  CASE WHEN l1.lms_email IS NOT NULL THEN 'EMAIL_EXACT'
       WHEN l2.lms_email IS NOT NULL THEN 'EMAIL_LOCALPART' END AS LMS_MATCH_METHOD,
  f.AID_ID                                                    AS AID_ID,
  c.CRM_CONTACT_ID                                            AS CRM_CONTACT_ID,
  r.CARD_ID                                                   AS CARD_ID,
  b.ACCOUNT_NO                                                AS BURSAR_ACCOUNT_NO
FROM RAW.SIS_STUDENT s
LEFT JOIN lms l1 ON l1.lms_email = LOWER(s.EMAIL)
LEFT JOIN lms l2 ON SPLIT_PART(l2.lms_email, '@', 1) = SPLIT_PART(LOWER(s.EMAIL), '@', 1)
LEFT JOIN RAW.FINAID_AWARD f      ON f.STUDENT_NUMBER = TO_NUMBER(SUBSTR(s.STUDENT_ID, 2))
LEFT JOIN RAW.ADVISING_CONTACT c  ON c.STUDENT_REF = 'STU-' || SUBSTR(s.STUDENT_ID, 2)
LEFT JOIN RAW.ID_CARD_ROSTER r    ON LOWER(r.EMAIL) = LOWER(s.EMAIL)
LEFT JOIN RAW.BURSAR_ACCOUNT b    ON b.STUDENT_ID = s.STUDENT_ID;
SELECT COUNT(*) AS STUDENTS FROM CURATED.STUDENT_XWALK;
""")

n.md("""### 📌 Measure the match rate (a data-quality gate)

Never ship an identity graph without a match report. Anything unresolved needs an owner.""")
n.sql("match_report", "Identity match report", """
SELECT 'LMS'        AS SOURCE, COUNT(LMS_EMAIL)        AS MATCHED, COUNT(*) AS STUDENTS, ROUND(100 * COUNT(LMS_EMAIL) / COUNT(*), 1) AS MATCH_PCT FROM CURATED.STUDENT_XWALK
UNION ALL SELECT 'FINANCIAL AID', COUNT(AID_ID), COUNT(*), ROUND(100 * COUNT(AID_ID) / COUNT(*), 1) FROM CURATED.STUDENT_XWALK
UNION ALL SELECT 'ADVISING CRM',  COUNT(CRM_CONTACT_ID), COUNT(*), ROUND(100 * COUNT(CRM_CONTACT_ID) / COUNT(*), 1) FROM CURATED.STUDENT_XWALK
UNION ALL SELECT 'CAMPUS CARD',   COUNT(CARD_ID), COUNT(*), ROUND(100 * COUNT(CARD_ID) / COUNT(*), 1) FROM CURATED.STUDENT_XWALK
UNION ALL SELECT 'BURSAR',        COUNT(BURSAR_ACCOUNT_NO), COUNT(*), ROUND(100 * COUNT(BURSAR_ACCOUNT_NO) / COUNT(*), 1) FROM CURATED.STUDENT_XWALK;
""")
n.sql("match_methods", "LMS match methods + orphans", """
-- How did LMS students match?  EMAIL_LOCALPART rows are the legacy-domain rescues.
SELECT LMS_MATCH_METHOD, COUNT(*) AS STUDENTS FROM CURATED.STUDENT_XWALK GROUP BY 1 ORDER BY 2 DESC;

-- LMS accounts that belong to NO student (test / service accounts) - flag them to the LMS owner.
SELECT COUNT(DISTINCT LOWER(a.LMS_USER_EMAIL)) AS ORPHAN_LMS_ACCOUNTS
FROM RAW.LMS_ACTIVITY a
LEFT JOIN CURATED.STUDENT_XWALK x ON x.LMS_EMAIL = LOWER(a.LMS_USER_EMAIL)
WHERE x.STUDENT_ID IS NULL;
""")

n.md("""## Step 2: Feature Tables (one per source)

🛠️ Each source gets its own small dynamic table that reduces it to **one row per student**. Keeping them separate means each can be owned, tested and refreshed independently, and the final join stays readable.""")

n.sql("create_academic", "Academic features", f"""
CREATE OR REPLACE DYNAMIC TABLE CURATED.FEAT_ACADEMIC
  TARGET_LAG = '1 hour' REFRESH_MODE = INCREMENTAL WAREHOUSE = {WH}
  COMMENT = 'Per-student academic features from SIS enrollments'
AS
SELECT
  STUDENT_ID,
  ROUND(SUM(IFF(ENROLLMENT_STATUS = 'COMPLETED', GRADE_POINTS * CREDITS, NULL))
        / NULLIF(SUM(IFF(ENROLLMENT_STATUS = 'COMPLETED', CREDITS, NULL)), 0), 2)    AS PRIOR_TERMS_GPA,
  COUNT_IF(TERM = 'Fall 2026')                                                      AS CURRENT_COURSES,
  SUM(IFF(TERM = 'Fall 2026', CREDITS, 0))                                           AS CURRENT_CREDITS,
  ROUND(SUM(IFF(TERM = 'Fall 2026', GRADE_POINTS * CREDITS, NULL))
        / NULLIF(SUM(IFF(TERM = 'Fall 2026', CREDITS, NULL)), 0), 2)                 AS MIDTERM_GPA,
  COUNT_IF(TERM = 'Fall 2026' AND MIDTERM_GRADE IN ('D','F'))                        AS MIDTERM_DF_COUNT,
  COUNT_IF(ENROLLMENT_STATUS = 'WITHDRAWN')                                          AS COURSE_WITHDRAWALS
FROM RAW.SIS_ENROLLMENT
GROUP BY STUDENT_ID;
SELECT COUNT(*) AS ROWS_ FROM CURATED.FEAT_ACADEMIC;
""")

n.sql("create_lms_feat", "LMS features", f"""
CREATE OR REPLACE DYNAMIC TABLE CURATED.FEAT_LMS
  TARGET_LAG = '1 hour' REFRESH_MODE = INCREMENTAL WAREHOUSE = {WH}
  COMMENT = 'Per-student LMS engagement features (Fall 2026), resolved through the crosswalk'
AS
SELECT
  x.STUDENT_ID,
  ROUND(AVG(IFF(a.WEEK_NUM <= 3, a.LOGINS, NULL)), 1)  AS AVG_LOGINS_EARLY,
  ROUND(AVG(IFF(a.WEEK_NUM >= 8, a.LOGINS, NULL)), 1)  AS AVG_LOGINS_RECENT,
  ROUND((AVG(IFF(a.WEEK_NUM >= 8, a.LOGINS, NULL)) - AVG(IFF(a.WEEK_NUM <= 3, a.LOGINS, NULL)))
        / NULLIF(AVG(IFF(a.WEEK_NUM <= 3, a.LOGINS, NULL)), 0), 3) AS LOGIN_TREND_PCT,
  ROUND(SUM(a.ASSIGNMENTS_SUBMITTED) / NULLIF(SUM(a.ASSIGNMENTS_DUE), 0), 3)  AS ASSIGNMENT_SUBMISSION_RATE,
  ROUND(AVG(a.AVG_SCORE_PCT), 1)                       AS AVG_LMS_SCORE_PCT
FROM RAW.LMS_ACTIVITY a
JOIN CURATED.STUDENT_XWALK x ON x.LMS_EMAIL = LOWER(a.LMS_USER_EMAIL)
GROUP BY x.STUDENT_ID;
SELECT COUNT(*) AS ROWS_ FROM CURATED.FEAT_LMS;
""")

n.sql("create_fin_feat", "Financial features", f"""
CREATE OR REPLACE DYNAMIC TABLE CURATED.FEAT_FINANCIAL
  TARGET_LAG = '1 hour' REFRESH_MODE = INCREMENTAL WAREHOUSE = {WH}
  COMMENT = 'Per-student financial features from Financial Aid and Bursar'
AS
SELECT
  x.STUDENT_ID,
  f.COST_OF_ATTENDANCE, f.GRANTS_AND_SCHOLARSHIPS, f.LOANS, f.UNMET_NEED, f.PELL_ELIGIBLE, f.SAP_STATUS,
  b.BALANCE_DUE, b.DAYS_PAST_DUE, b.HOLD_TYPE, b.PAYMENT_PLAN_FLAG
FROM CURATED.STUDENT_XWALK x
LEFT JOIN RAW.FINAID_AWARD f ON f.AID_ID = x.AID_ID
LEFT JOIN RAW.BURSAR_ACCOUNT b ON b.ACCOUNT_NO = x.BURSAR_ACCOUNT_NO;
SELECT COUNT(*) AS ROWS_ FROM CURATED.FEAT_FINANCIAL;
""")

n.sql("create_campus_feat", "Campus engagement features", f"""
CREATE OR REPLACE DYNAMIC TABLE CURATED.FEAT_CAMPUS
  TARGET_LAG = '1 hour' REFRESH_MODE = INCREMENTAL WAREHOUSE = {WH}
  COMMENT = 'Per-student campus engagement from ID-card swipes (Fall 2026)'
AS
SELECT
  x.STUDENT_ID,
  ROUND(AVG(c.LIBRARY_VISITS), 1)    AS AVG_WEEKLY_LIBRARY_VISITS,
  ROUND(AVG(c.REC_CENTER_VISITS), 1) AS AVG_WEEKLY_REC_VISITS,
  ROUND(AVG(c.DINING_SWIPES), 1)     AS AVG_WEEKLY_DINING_SWIPES,
  SUM(c.EVENTS_ATTENDED)             AS EVENTS_ATTENDED_TERM,
  ROUND(AVG(c.LIBRARY_VISITS + c.REC_CENTER_VISITS + c.EVENTS_ATTENDED), 1) AS CAMPUS_TOUCHPOINTS_PER_WEEK
FROM RAW.CAMPUS_ENGAGEMENT c
JOIN CURATED.STUDENT_XWALK x ON x.CARD_ID = c.CARD_ID
GROUP BY x.STUDENT_ID;
SELECT COUNT(*) AS ROWS_ FROM CURATED.FEAT_CAMPUS;
""")

n.md("""## Step 3: Enrich the Unstructured Advising Notes with Cortex AI

🛠️ Advisors write free text. Two Cortex AI functions turn it into something governable and queryable:

| Function | What it does here |
|---|---|
| `AI_REDACT` | Removes names, phone numbers and emails from the note text, so the *only* version the agent can ever see is PII-free |
| `AI_CLASSIFY` | Tags each note with a theme (financial hardship, wellbeing, academic struggle, considering leaving, on track) so concerns become filterable and countable |

✅ **Best practice - redact at the data layer, not in the prompt.** An agent instruction saying "do not reveal phone numbers" is a request. Removing the phone number before the agent can read it is a guarantee.

🔹 We use a regular table (CTAS) rather than a dynamic table because AI functions are billed per row - you decide when to re-run them. For production, schedule incremental enrichment with a **stream + task** so only *new* notes are processed.""")
n.sql("create_notes_enriched", "Enrich advising notes", """
CREATE OR REPLACE TABLE CURATED.ADVISING_NOTE_ENRICHED
COMMENT = 'Advising notes resolved to STUDENT_ID, PII-redacted (AI_REDACT) and theme-tagged (AI_CLASSIFY). Raw text is NOT carried forward.'
AS
SELECT
  n.NOTE_ID,
  x.STUDENT_ID,
  s.COLLEGE,
  n.NOTE_DATE,
  n.ADVISOR_NAME,
  n.NOTE_TYPE,
  AI_REDACT(n.NOTE_TEXT)::STRING AS NOTE_TEXT_REDACTED,
  AI_CLASSIFY(n.NOTE_TEXT,
    ['financial hardship', 'mental health and wellbeing', 'academic struggle', 'considering leaving', 'on track']):labels[0]::STRING AS NOTE_THEME
FROM RAW.ADVISING_NOTE n
JOIN CURATED.STUDENT_XWALK x ON x.CRM_CONTACT_ID = n.CRM_CONTACT_ID
JOIN RAW.SIS_STUDENT s ON s.STUDENT_ID = x.STUDENT_ID;
ALTER TABLE CURATED.ADVISING_NOTE_ENRICHED ADD COLUMN CONCERN_FLAG BOOLEAN;
UPDATE CURATED.ADVISING_NOTE_ENRICHED SET CONCERN_FLAG = (NOTE_THEME <> 'on track');
SELECT NOTE_THEME, COUNT(*) AS NOTES FROM CURATED.ADVISING_NOTE_ENRICHED GROUP BY 1 ORDER BY 2 DESC;
""")
n.sql("check_redaction", "Verify redaction worked", """
-- Raw notes with PII vs. redacted notes still containing a phone number or gmail address (expect 0)
SELECT
  (SELECT COUNT(*) FROM RAW.ADVISING_NOTE WHERE NOTE_TEXT LIKE '%555-%' OR NOTE_TEXT ILIKE '%@gmail.com%') AS RAW_NOTES_WITH_PII,
  (SELECT COUNT(*) FROM CURATED.ADVISING_NOTE_ENRICHED WHERE NOTE_TEXT_REDACTED LIKE '%555-%' OR NOTE_TEXT_REDACTED ILIKE '%@gmail.com%') AS REDACTED_NOTES_WITH_PII;

-- Side-by-side example
SELECT r.NOTE_TEXT AS RAW_TEXT, e.NOTE_TEXT_REDACTED
FROM RAW.ADVISING_NOTE r JOIN CURATED.ADVISING_NOTE_ENRICHED e USING (NOTE_ID)
WHERE r.NOTE_TEXT LIKE '%555-%' LIMIT 2;
""")

n.sql("create_adv_feat", "Advising features", f"""
CREATE OR REPLACE DYNAMIC TABLE CURATED.FEAT_ADVISING
  TARGET_LAG = '1 hour' REFRESH_MODE = INCREMENTAL WAREHOUSE = {WH}
  COMMENT = 'Per-student advising features derived from enriched notes'
AS
SELECT
  STUDENT_ID,
  COUNT(*)                                     AS ADVISING_NOTES_TERM,
  COUNT_IF(CONCERN_FLAG)                       AS CONCERN_NOTES,
  MAX(NOTE_DATE)                               AS LAST_ADVISING_DATE,
  DATEDIFF('day', MAX(NOTE_DATE), '2026-11-02'::DATE) AS DAYS_SINCE_ADVISING,
  MAX_BY(IFF(CONCERN_FLAG, NOTE_THEME, NULL), IFF(CONCERN_FLAG, NOTE_DATE, NULL)) AS LATEST_CONCERN_THEME
FROM CURATED.ADVISING_NOTE_ENRICHED
GROUP BY STUDENT_ID;
SELECT COUNT(*) AS ROWS_ FROM CURATED.FEAT_ADVISING;
""")

n.md("""## Step 4: Assemble the `STUDENT_360`

🛠️ One row per student. Three things to notice in the SQL:

1. **Every join is a LEFT JOIN from the SIS roster.** A student missing from a source (no aid record, no card) must still appear - and `DATA_SOURCES_COVERED` tells you how complete the picture is.
2. **The risk score is a transparent rule set, not a black box.** Each rule adds points and records a human-readable driver, so an advisor (and the agent) can always answer *why*.
3. **PII columns (email, phone, date of birth) are kept** here - they are governed with masking policies in Notebook 03, not dropped, because advisors legitimately need them.

📌 *The risk score is a **triage signal to prioritise outreach**, never a verdict about a student.* We encode that rule in the agent's instructions in Notebook 04.

🔹 `'2026-11-02'` is the as-of date (week 10 of Fall 2026) so the lab is repeatable. In production use `CURRENT_DATE()` (dynamic tables then refresh in full mode for that column - acceptable for a table this size).""")
n.sql("create_student360", "Create STUDENT_360", f"""
CREATE OR REPLACE DYNAMIC TABLE CURATED.STUDENT_360
  TARGET_LAG = '1 hour' REFRESH_MODE = INCREMENTAL WAREHOUSE = {WH}
  COMMENT = 'Student 360: one row per student unifying SIS, LMS, Financial Aid, Bursar, Advising CRM and Campus Card, with an explainable retention-risk score. As of week 10, Fall 2026.'
AS
WITH base AS (
  SELECT
    s.STUDENT_ID, s.FIRST_NAME, s.LAST_NAME, s.FIRST_NAME || ' ' || s.LAST_NAME AS FULL_NAME,
    s.EMAIL, s.PHONE, s.DATE_OF_BIRTH,
    s.COLLEGE, s.MAJOR, s.CLASS_LEVEL, s.ADMIT_TERM, s.ENROLLMENT_STATUS, s.FIRST_GEN_FLAG, s.RESIDENCY,
    COALESCE(s.CUMULATIVE_GPA, ac.MIDTERM_GPA)  AS CURRENT_GPA,
    s.CUMULATIVE_GPA, s.CREDITS_EARNED,
    ac.MIDTERM_GPA, ac.CURRENT_COURSES, ac.CURRENT_CREDITS, ac.MIDTERM_DF_COUNT, ac.COURSE_WITHDRAWALS,
    l.AVG_LOGINS_EARLY, l.AVG_LOGINS_RECENT, l.LOGIN_TREND_PCT, l.ASSIGNMENT_SUBMISSION_RATE, l.AVG_LMS_SCORE_PCT,
    f.COST_OF_ATTENDANCE, f.UNMET_NEED, f.PELL_ELIGIBLE, f.SAP_STATUS,
    f.BALANCE_DUE, f.DAYS_PAST_DUE, COALESCE(f.HOLD_TYPE, 'NONE') AS HOLD_TYPE,
    cp.CAMPUS_TOUCHPOINTS_PER_WEEK, cp.AVG_WEEKLY_LIBRARY_VISITS, cp.AVG_WEEKLY_DINING_SWIPES, cp.EVENTS_ATTENDED_TERM,
    COALESCE(av.ADVISING_NOTES_TERM, 0) AS ADVISING_NOTES_TERM, COALESCE(av.CONCERN_NOTES, 0) AS CONCERN_NOTES,
    av.LAST_ADVISING_DATE, COALESCE(av.DAYS_SINCE_ADVISING, 999) AS DAYS_SINCE_ADVISING, av.LATEST_CONCERN_THEME,
    c.ASSIGNED_ADVISOR,
    (1 + IFF(l.STUDENT_ID IS NOT NULL,1,0) + IFF(f.UNMET_NEED IS NOT NULL OR f.BALANCE_DUE IS NOT NULL,1,0)
       + IFF(cp.STUDENT_ID IS NOT NULL,1,0) + IFF(av.STUDENT_ID IS NOT NULL,1,0) + IFF(ac.STUDENT_ID IS NOT NULL,1,0)) AS DATA_SOURCES_COVERED
  FROM RAW.SIS_STUDENT s
  LEFT JOIN CURATED.FEAT_ACADEMIC  ac ON ac.STUDENT_ID = s.STUDENT_ID
  LEFT JOIN CURATED.FEAT_LMS        l ON  l.STUDENT_ID = s.STUDENT_ID
  LEFT JOIN CURATED.FEAT_FINANCIAL  f ON  f.STUDENT_ID = s.STUDENT_ID
  LEFT JOIN CURATED.FEAT_CAMPUS    cp ON cp.STUDENT_ID = s.STUDENT_ID
  LEFT JOIN CURATED.FEAT_ADVISING  av ON av.STUDENT_ID = s.STUDENT_ID
  LEFT JOIN CURATED.STUDENT_XWALK  xw ON xw.STUDENT_ID = s.STUDENT_ID
  LEFT JOIN RAW.ADVISING_CONTACT    c ON  c.CRM_CONTACT_ID = xw.CRM_CONTACT_ID
),
rules AS (
  SELECT b.*,
    IFF(CURRENT_GPA < 2.0, 25, IFF(CURRENT_GPA < 2.5, 15, IFF(CURRENT_GPA < 3.0, 5, 0)))        AS p_gpa,
    IFF(MIDTERM_DF_COUNT >= 2, 15, IFF(MIDTERM_DF_COUNT = 1, 8, 0))                              AS p_midterm,
    IFF(LOGIN_TREND_PCT <= -0.4, 15, IFF(LOGIN_TREND_PCT <= -0.2, 7, 0))                          AS p_lms_trend,
    IFF(ASSIGNMENT_SUBMISSION_RATE < 0.6, 10, IFF(ASSIGNMENT_SUBMISSION_RATE < 0.8, 4, 0))        AS p_submit,
    IFF(CAMPUS_TOUCHPOINTS_PER_WEEK < 2.5, 5, 0)                                                  AS p_campus,
    IFF(UNMET_NEED >= 8000, 10, IFF(UNMET_NEED >= 4000, 5, 0))                                    AS p_unmet,
    IFF(HOLD_TYPE <> 'NONE', 10, 0)                                                               AS p_hold,
    IFF(CONCERN_NOTES >= 2, 10, IFF(CONCERN_NOTES = 1, 6, 0))                                     AS p_concern,
    IFF(DAYS_SINCE_ADVISING > 45, 5, 0)                                                           AS p_no_contact
  FROM base b
)
SELECT
  STUDENT_ID, FIRST_NAME, LAST_NAME, FULL_NAME, EMAIL, PHONE, DATE_OF_BIRTH,
  COLLEGE, MAJOR, CLASS_LEVEL, ADMIT_TERM, ENROLLMENT_STATUS, FIRST_GEN_FLAG, RESIDENCY, ASSIGNED_ADVISOR,
  CURRENT_GPA, CUMULATIVE_GPA, CREDITS_EARNED, MIDTERM_GPA, CURRENT_COURSES, CURRENT_CREDITS, MIDTERM_DF_COUNT, COURSE_WITHDRAWALS,
  AVG_LOGINS_EARLY, AVG_LOGINS_RECENT, LOGIN_TREND_PCT, ASSIGNMENT_SUBMISSION_RATE, AVG_LMS_SCORE_PCT,
  COST_OF_ATTENDANCE, UNMET_NEED, PELL_ELIGIBLE, SAP_STATUS, BALANCE_DUE, DAYS_PAST_DUE, HOLD_TYPE,
  CAMPUS_TOUCHPOINTS_PER_WEEK, AVG_WEEKLY_LIBRARY_VISITS, AVG_WEEKLY_DINING_SWIPES, EVENTS_ATTENDED_TERM,
  ADVISING_NOTES_TERM, CONCERN_NOTES, LAST_ADVISING_DATE, DAYS_SINCE_ADVISING, LATEST_CONCERN_THEME,
  DATA_SOURCES_COVERED,
  LEAST(100, p_gpa + p_midterm + p_lms_trend + p_submit + p_campus + p_unmet + p_hold + p_concern + p_no_contact) AS RETENTION_RISK_SCORE,
  CASE WHEN LEAST(100, p_gpa + p_midterm + p_lms_trend + p_submit + p_campus + p_unmet + p_hold + p_concern + p_no_contact) >= 60 THEN 'HIGH'
       WHEN LEAST(100, p_gpa + p_midterm + p_lms_trend + p_submit + p_campus + p_unmet + p_hold + p_concern + p_no_contact) >= 30 THEN 'MEDIUM'
       ELSE 'LOW' END AS RISK_TIER,
  ARRAY_TO_STRING(ARRAY_COMPACT(ARRAY_CONSTRUCT(
    IFF(p_gpa >= 15,      'Low GPA', NULL),
    IFF(p_midterm >= 8,   'Failing/near-failing midterm grades', NULL),
    IFF(p_lms_trend >= 7, 'Declining LMS logins', NULL),
    IFF(p_submit >= 4,    'Missing assignments', NULL),
    IFF(p_campus > 0,     'Low campus engagement', NULL),
    IFF(p_unmet >= 5,     'Unmet financial need', NULL),
    IFF(p_hold > 0,       'Account hold', NULL),
    IFF(p_concern > 0,    'Advisor-noted concern', NULL),
    IFF(p_no_contact > 0, 'No recent advising contact', NULL))), '; ') AS TOP_RISK_DRIVERS
FROM rules
WHERE ENROLLMENT_STATUS = 'ACTIVE';
SELECT COUNT(*) AS STUDENTS FROM CURATED.STUDENT_360;
""")

n.sql("check_360", "Sanity-check the Student 360", """
-- 1) Risk distribution
SELECT RISK_TIER, COUNT(*) AS STUDENTS, ROUND(AVG(RETENTION_RISK_SCORE), 1) AS AVG_SCORE, ROUND(AVG(CURRENT_GPA), 2) AS AVG_GPA
FROM CURATED.STUDENT_360 GROUP BY 1 ORDER BY 3 DESC;

-- 2) Source coverage (how complete is each student's picture?)
SELECT DATA_SOURCES_COVERED, COUNT(*) AS STUDENTS FROM CURATED.STUDENT_360 GROUP BY 1 ORDER BY 1 DESC;

-- 3) A high-risk student, end to end
SELECT STUDENT_ID, FULL_NAME, COLLEGE, MAJOR, CURRENT_GPA, LOGIN_TREND_PCT, UNMET_NEED, HOLD_TYPE, CONCERN_NOTES,
       RETENTION_RISK_SCORE, RISK_TIER, TOP_RISK_DRIVERS
FROM CURATED.STUDENT_360 WHERE RISK_TIER = 'HIGH' ORDER BY RETENTION_RISK_SCORE DESC LIMIT 5;
""")

n.md("""### 🎓 Why this is trustworthy enough for AI

| Property | How we got it |
|---|---|
| **One row per student, guaranteed** | Driven from the SIS roster; every other join is a LEFT JOIN onto a one-row-per-student feature table |
| **Explainable** | `TOP_RISK_DRIVERS` shows which rules fired - the agent can always say *why* |
| **Fresh** | Dynamic tables refresh to the declared `TARGET_LAG`; no orchestration code |
| **PII-safe text** | Only the `AI_REDACT`ed notes flow downstream |
| **Measurable** | Match-rate report + `DATA_SOURCES_COVERED` expose gaps instead of hiding them |

### 📌 Going further (production)
- Replace the rule-based score with a **Snowflake ML classification model** trained on prior-year outcomes (`SNOWFLAKE.ML.CLASSIFICATION`), keeping `TOP_RISK_DRIVERS` via feature importance.
- Add **data metric functions** (`SNOWFLAKE.CORE.NULL_COUNT`, `DUPLICATE_COUNT`) on `STUDENT_360.STUDENT_ID` to alert when identity resolution regresses.
- Ingest the real sources with Openflow / Snowpipe / partner connectors into `RAW`; this notebook then works unchanged.""")

n.footer([
    "`CURATED.STUDENT_XWALK` - identity crosswalk with match methods and a match-rate report",
    "Five per-source feature dynamic tables (academic, LMS, financial, campus, advising)",
    "`CURATED.ADVISING_NOTE_ENRICHED` - PII-redacted, theme-classified advising notes",
    "`CURATED.STUDENT_360` - one governed row per active student with an explainable retention-risk score",
],
    [
        "Resolve identity deterministically first; keep the match method and report the match rate.",
        "Separate feature tables per source; one assembly table. Dynamic tables keep it all fresh declaratively.",
        "Redact PII in the data layer before any AI can read it; AI functions turn free text into governable columns.",
        "Make scores explainable - drivers, not just a number.",
    ],
    "**Notebook 02** - give the agent meaning: a governed semantic view plus Cortex Search services.")
n.write()
