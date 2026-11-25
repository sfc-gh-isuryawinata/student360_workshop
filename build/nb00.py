from lib import NB, DB, ROLE, WH

FN = "'Maria','James','Aisha','Wei','Carlos','Priya','Liam','Fatima','Noah','Sofia','Daniel','Mei','Omar','Emma','Jamal','Hannah','Diego','Yuki','Grace','Ethan','Olivia','Mateo','Amara','Lucas','Isabella','Kenji','Zara','Henry','Layla','Samuel','Chloe','Andre','Nia','Tyler','Elena','Rahul','Megan','Hassan','Lily','Victor','Anika','Jack','Camila','Ravi','Sienna','Marcus','Leila','Owen','Tessa','Bilal'"
LN = "'Garcia','Nguyen','Johnson','Patel','Kim','Hernandez','Smith','Okafor','Chen','Martinez','Brown','Singh','Lopez','Davis','Tanaka','Wilson','Ahmed','Rossi','Cohen','Mitchell','Thompson','Reyes','Abdi','Kowalski','Fernandez','Park','Walker','Hussain','Moreau','Bennett','Yamamoto','Castillo','Adeyemi','Foster','Ivanov','Murphy','Das','Silva','Young','Haddad'"

n = NB("Notebook_00_Lab_Setup.ipynb", 0, "Lab Setup & Source Data", "Phase 0 - Build the sandbox", 20)
n.header([
    "🛠️ Creates an **isolated lab role, database and schemas** (`STUDENT360_LAB`) so nothing collides with other work on a shared account",
    "🛠️ Creates an **XS warehouse** and the focused grants the lab role needs",
    "🛠️ Loads **six simulated Lakeside University source systems** into a `RAW` schema - each with its *own* student key format, exactly like a real campus: SIS, LMS, Financial Aid, Bursar, Advising CRM (structured + unstructured notes) and Campus ID-card swipes",
],
    "A Student 360 is only as good as the sources feeding it. Real campuses never share one student key, so we start from deliberately messy, siloed data and spend the next notebook resolving it.",
    "`ACCOUNTADMIN` (or a role that can create roles, databases and warehouses)")

n.md("""## 🎓 The scenario: Lakeside University

Lakeside University (about 2,000 students in this lab) loses students every year and finds out too late. The signals that predict a student stopping out already exist - they are just scattered across six systems owned by six different departments:

| Source system | Owner | Student key it uses | What it knows |
|---|---|---|---|
| **SIS** (Student Information System) | Registrar | `S0000123` | Demographics, college, major, class level, GPA, course enrollments and grades |
| **LMS** (Learning Management System) | Academic Technology | login **email** (mixed case, some on a legacy domain) | Weekly logins, minutes active, assignment submission, scores |
| **Financial Aid** | Financial Aid Office | `FA-100007` + **bare number** `123` | Aid package, unmet need, satisfactory-academic-progress status |
| **Bursar** | Student Accounts | `S0000123` | Balance due, days past due, registration / financial holds |
| **Advising CRM** | Advising Center | `C-123` + `STU-0000123` | Assigned advisor, free-text **advising notes** (unstructured, contains PII) |
| **Campus ID card** | Campus Card Office | `CARD…` joined by **email** | Library, rec-center, dining and event swipes |

The goal of the workshop: **one governed row per student** (the *Student 360*), an AI agent on top of it that advisors can talk to in CoWork, and the production practices around it (access, cost, evaluation, promotion).

> 📌 All data is **synthetic**. No real student records are used.""")

n.md("""## Step 1: Create the Lab Role

🛠️ A dedicated role owns everything we build, so the whole lab can be granted and dropped as a unit - and nothing runs as `ACCOUNTADMIN` that does not have to.""")
n.sql("create_role", "Create Lab Role", f"""
USE ROLE ACCOUNTADMIN;
CREATE ROLE IF NOT EXISTS {ROLE} COMMENT = 'Student 360 workshop lab role';
GRANT ROLE {ROLE} TO ROLE ACCOUNTADMIN;
SET me = CURRENT_USER();
GRANT ROLE {ROLE} TO USER IDENTIFIER($me);
SELECT '{ROLE} created and granted' AS STATUS;
""")

n.md("""## Step 2: Create the Database & Schemas

🛠️ Five schemas separate concerns - this layout is reused in every later notebook:

| Schema | Purpose |
|---|---|
| `RAW` | Source-system extracts exactly as they land (never edited) |
| `CURATED` | Identity-resolved, feature-engineered Student 360 (the *gold* layer) |
| `GOVERNANCE` | Policies, role-to-college scope table |
| `SEMANTIC` | Governed semantic view the agent queries |
| `AGENTS` | Agent, search services, evaluation data, budgets |

✅ **Best practice:** keep raw, curated and AI-serving objects in separate schemas so you can grant the agent's role the *serving* layer only.""")
n.sql("create_db", "Create Database & Schemas", f"""
USE ROLE ACCOUNTADMIN;
CREATE DATABASE IF NOT EXISTS {DB} COMMENT = 'Student 360 + CoWork workshop (Higher Ed)';
CREATE SCHEMA IF NOT EXISTS {DB}.RAW        COMMENT = 'Simulated source systems';
CREATE SCHEMA IF NOT EXISTS {DB}.CURATED    COMMENT = 'Identity-resolved Student 360';
CREATE SCHEMA IF NOT EXISTS {DB}.GOVERNANCE COMMENT = 'Policies and access scope';
CREATE SCHEMA IF NOT EXISTS {DB}.SEMANTIC   COMMENT = 'Semantic views';
CREATE SCHEMA IF NOT EXISTS {DB}.AGENTS     COMMENT = 'Agents, search services, eval data';
GRANT OWNERSHIP ON ALL SCHEMAS IN DATABASE {DB} TO ROLE {ROLE} REVOKE CURRENT GRANTS;
GRANT OWNERSHIP ON DATABASE {DB} TO ROLE {ROLE} COPY CURRENT GRANTS;
SELECT 'Database and schemas ready' AS STATUS;
""")

n.md("""## Step 3: Create the Warehouse & Grant Privileges

🛠️ An XS warehouse runs the lab's SQL (agent LLM reasoning is serverless and billed separately). The grants give the lab role exactly what it needs to create dynamic tables, semantic views, search services and agents.

🔹 `SNOWFLAKE.CORTEX_USER` entitles a role to call Cortex AI functions (we use `AI_CLASSIFY` and `AI_REDACT` in Notebook 01).""")
n.sql("create_wh_grants", "Warehouse & Grants", f"""
USE ROLE ACCOUNTADMIN;
CREATE WAREHOUSE IF NOT EXISTS {WH}
  WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Student 360 workshop warehouse';
GRANT OWNERSHIP ON WAREHOUSE {WH} TO ROLE {ROLE} COPY CURRENT GRANTS;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE {ROLE};
GRANT CREATE ROLE ON ACCOUNT TO ROLE {ROLE};
GRANT CREATE USER ON ACCOUNT TO ROLE {ROLE};
GRANT CREATE SNOWFLAKE INTELLIGENCE ON ACCOUNT TO ROLE {ROLE};
GRANT EXECUTE TASK ON ACCOUNT TO ROLE {ROLE};
SELECT 'Warehouse + grants ready' AS STATUS;
""")

n.md("""## Step 4: Enable Cross-Region Inference

🔹 Cortex may route a request to an LLM hosted in another region. This account-level setting permits that (needed for some models and for agent evaluations). It is a **safe no-op** if already set.""")
n.sql("cross_region", "Enable Cross-Region Inference", """
USE ROLE ACCOUNTADMIN;
ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';
SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;
""")

n.md("""## Step 5: Load the Six Source Systems

🛠️ Each cell below builds one source system, deterministically (hash-based - the same data every run, no random seed needed). A hidden helper `RAW.SIM_RISK(n)` drives a latent "likelihood of leaving" that subtly shapes every source (lower GPA, fading LMS logins, unmet financial need, concerned advisor notes ...), so the Student 360 you build in Notebook 01 has real signal to find.

> 🔹 Notice what makes this *realistic*: six different key formats, mixed-case emails, a legacy email domain for ~3% of LMS accounts, LMS test accounts that belong to no student, and ~15% of students with no financial-aid record.""")

n.sql("set_context", "Set Context", f"""
USE ROLE {ROLE};
USE DATABASE {DB};
USE SCHEMA RAW;
USE WAREHOUSE {WH};
SELECT CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE();
""")

n.sql("sim_helper", "Simulation helper", """
CREATE OR REPLACE FUNCTION RAW.SIM_RISK(N NUMBER)
  RETURNS FLOAT
  COMMENT = 'SIMULATION ONLY - latent 0..1 churn propensity used to generate correlated synthetic data'
  AS $$ POWER((ABS(HASH(N, 'risk')) % 1000) / 1000.0, 1.8)::FLOAT $$;
SELECT RAW.SIM_RISK(1) AS example;
""")

n.md("### 5a. SIS - students and course enrollments (Registrar)")
n.sql("load_sis_student", "SIS: Students", f"""
CREATE OR REPLACE TABLE RAW.SIS_STUDENT
COMMENT = 'Registrar SIS - one row per student. Key: STUDENT_ID (S + 7 digits)' AS
WITH g AS (SELECT SEQ4() + 1 AS n FROM TABLE(GENERATOR(ROWCOUNT => 2000))),
b AS (
  SELECT n, RAW.SIM_RISK(n) AS r,
    GET(ARRAY_CONSTRUCT({FN}), MOD(n, 50))::STRING AS fn,
    GET(ARRAY_CONSTRUCT({LN}), MOD(FLOOR(n / 50), 40))::STRING AS ln,
    GET(ARRAY_CONSTRUCT('Engineering','Arts & Sciences','Business','Nursing & Health','Education'), MOD(ABS(HASH(n,'col')), 5))::STRING AS college,
    GET(ARRAY_CONSTRUCT('Freshman','Sophomore','Junior','Senior'), MOD(ABS(HASH(n,'cl')), 4))::STRING AS class_level
  FROM g
)
SELECT
  'S' || LPAD(n, 7, '0') AS STUDENT_ID,
  fn AS FIRST_NAME, ln AS LAST_NAME,
  LOWER(fn || '.' || ln || n || '@lakeside.edu') AS EMAIL,
  '555-' || LPAD(MOD(ABS(HASH(n,'ph')), 10000), 4, '0') AS PHONE,
  DATEADD(day, -(18*365 + MOD(ABS(HASH(n,'dob')), 1500)), '2026-08-24'::DATE) AS DATE_OF_BIRTH,
  college AS COLLEGE,
  CASE college
    WHEN 'Engineering'      THEN GET(ARRAY_CONSTRUCT('Mechanical Engineering','Computer Science','Electrical Engineering','Civil Engineering'), MOD(ABS(HASH(n,'maj')), 4))
    WHEN 'Arts & Sciences'  THEN GET(ARRAY_CONSTRUCT('Biology','Psychology','English','Chemistry'), MOD(ABS(HASH(n,'maj')), 4))
    WHEN 'Business'         THEN GET(ARRAY_CONSTRUCT('Accounting','Marketing','Finance','Management'), MOD(ABS(HASH(n,'maj')), 4))
    WHEN 'Nursing & Health' THEN GET(ARRAY_CONSTRUCT('Nursing','Public Health','Kinesiology','Health Sciences'), MOD(ABS(HASH(n,'maj')), 4))
    ELSE GET(ARRAY_CONSTRUCT('Elementary Education','Secondary Education','Special Education','Counseling'), MOD(ABS(HASH(n,'maj')), 4))
  END::STRING AS MAJOR,
  class_level AS CLASS_LEVEL,
  CASE class_level WHEN 'Freshman' THEN 'Fall 2026' WHEN 'Sophomore' THEN 'Fall 2025' WHEN 'Junior' THEN 'Fall 2024' ELSE 'Fall 2023' END AS ADMIT_TERM,
  CASE WHEN r > 0.97 THEN 'WITHDRAWN' WHEN r > 0.93 THEN 'LEAVE_OF_ABSENCE' ELSE 'ACTIVE' END AS ENROLLMENT_STATUS,
  IFF(MOD(ABS(HASH(n,'fg')), 100) < 32, 'Y', 'N') AS FIRST_GEN_FLAG,
  GET(ARRAY_CONSTRUCT('In-State','In-State','Out-of-State','International'), MOD(ABS(HASH(n,'res')), 4))::STRING AS RESIDENCY,
  IFF(class_level = 'Freshman', NULL,
      ROUND(GREATEST(0.8, LEAST(4.0, 3.9 - r*2.4 + (MOD(ABS(HASH(n,'gn')), 61) - 30)/100.0)), 2)) AS CUMULATIVE_GPA,
  CASE class_level WHEN 'Freshman' THEN 0 WHEN 'Sophomore' THEN 28 WHEN 'Junior' THEN 60 ELSE 92 END
    + MOD(ABS(HASH(n,'cr')), 9) AS CREDITS_EARNED
FROM b;
SELECT COUNT(*) AS STUDENTS, COUNT_IF(ENROLLMENT_STATUS<>'ACTIVE') AS NOT_ACTIVE FROM RAW.SIS_STUDENT;
""")

n.sql("load_sis_enrollment", "SIS: Enrollments", """
CREATE OR REPLACE TABLE RAW.SIS_ENROLLMENT
COMMENT = 'Registrar SIS - one row per student per course per term' AS
WITH cat AS (
  SELECT column1 AS idx, column2 AS COURSE_CODE, column3 AS COURSE_TITLE, column4 AS DEPARTMENT, column5 AS CREDITS
  FROM VALUES
   (0,'MATH101','Calculus I','Mathematics',4),(1,'ENGL101','Composition','English',3),
   (2,'BIOL110','Intro Biology','Biology',4),(3,'CHEM101','General Chemistry','Chemistry',4),
   (4,'PSYC100','Intro Psychology','Psychology',3),(5,'CS110','Intro Programming','Computer Science',4),
   (6,'ECON201','Microeconomics','Economics',3),(7,'STAT200','Statistics','Mathematics',3),
   (8,'HIST150','World History','History',3),(9,'PHYS201','Physics I','Physics',4),
   (10,'ACCT210','Financial Accounting','Accounting',3),(11,'EDUC120','Foundations of Education','Education',3),
   (12,'NURS130','Health Assessment','Nursing',4),(13,'COMM101','Public Speaking','Communication',3),
   (14,'MGMT220','Principles of Management','Management',3),(15,'ENGR100','Engineering Design','Engineering',3)
),
terms AS (SELECT column1 AS TERM, column2 AS term_idx FROM VALUES ('Fall 2025',1),('Spring 2026',2),('Fall 2026',3)),
slots AS (SELECT SEQ4() AS slot FROM TABLE(GENERATOR(ROWCOUNT => 4))),
s AS (
  SELECT STUDENT_ID, ADMIT_TERM, ENROLLMENT_STATUS, TO_NUMBER(SUBSTR(STUDENT_ID, 2)) AS n,
         RAW.SIM_RISK(TO_NUMBER(SUBSTR(STUDENT_ID, 2))) AS r
  FROM RAW.SIS_STUDENT
),
x AS (
  SELECT s.STUDENT_ID, s.n, s.r, t.TERM, t.term_idx, sl.slot,
         MOD(ABS(HASH(s.n, t.TERM)) + sl.slot * 5, 16) AS cidx,
         3.8 - s.r * 2.6 + (MOD(ABS(HASH(s.n, t.TERM, sl.slot)), 161) - 80) / 100.0
           - CASE MOD(ABS(HASH(s.n, t.TERM)) + sl.slot * 5, 16) WHEN 0 THEN 0.6 WHEN 3 THEN 0.7 WHEN 9 THEN 0.6 WHEN 2 THEN 0.3 WHEN 7 THEN 0.3 ELSE 0 END AS score
  FROM s CROSS JOIN terms t CROSS JOIN slots sl
  WHERE (s.ADMIT_TERM <> 'Fall 2026' OR t.TERM = 'Fall 2026')
    AND NOT (t.TERM = 'Fall 2026' AND s.ENROLLMENT_STATUS IN ('WITHDRAWN','LEAVE_OF_ABSENCE'))
),
l AS (
  SELECT x.*, c.COURSE_CODE, c.COURSE_TITLE, c.DEPARTMENT, c.CREDITS,
    CASE WHEN score >= 3.7 THEN 'A' WHEN score >= 3.3 THEN 'B+' WHEN score >= 3.0 THEN 'B' WHEN score >= 2.7 THEN 'B-'
         WHEN score >= 2.0 THEN 'C' WHEN score >= 1.0 THEN 'D' ELSE 'F' END AS letter
  FROM x JOIN cat c ON c.idx = x.cidx
)
SELECT
  'E' || LPAD(ROW_NUMBER() OVER (ORDER BY STUDENT_ID, term_idx, slot), 8, '0') AS ENROLLMENT_ID,
  STUDENT_ID, TERM, COURSE_CODE, COURSE_TITLE, DEPARTMENT, CREDITS,
  IFF(TERM = 'Fall 2026', NULL, IFF(r > 0.7 AND MOD(ABS(HASH(n, TERM, slot, 'w')), 10) = 0, 'W', letter)) AS FINAL_GRADE,
  IFF(TERM = 'Fall 2026', letter, NULL) AS MIDTERM_GRADE,
  CASE IFF(TERM = 'Fall 2026', letter, IFF(r > 0.7 AND MOD(ABS(HASH(n, TERM, slot, 'w')), 10) = 0, 'W', letter))
    WHEN 'A' THEN 4.0 WHEN 'B+' THEN 3.3 WHEN 'B' THEN 3.0 WHEN 'B-' THEN 2.7 WHEN 'C' THEN 2.0 WHEN 'D' THEN 1.0 WHEN 'F' THEN 0.0 END AS GRADE_POINTS,
  CASE WHEN TERM = 'Fall 2026' THEN 'ENROLLED'
       WHEN r > 0.7 AND MOD(ABS(HASH(n, TERM, slot, 'w')), 10) = 0 THEN 'WITHDRAWN' ELSE 'COMPLETED' END AS ENROLLMENT_STATUS
FROM l;
SELECT TERM, COUNT(*) AS ROWS_, COUNT(DISTINCT STUDENT_ID) AS STUDENTS FROM RAW.SIS_ENROLLMENT GROUP BY TERM ORDER BY TERM;
""")

n.md("""### 5b. LMS - weekly course-site activity (Academic Technology)

🔹 Keyed by **login email** only - no student ID. ~3% of accounts use a legacy `@lakeside.com` domain and some are upper-cased. 25 LMS **test accounts** belong to no student. This is the classic "identity resolution" problem you solve in Notebook 01.""")
n.sql("load_lms", "LMS: Weekly activity", """
CREATE OR REPLACE TABLE RAW.LMS_ACTIVITY
COMMENT = 'LMS weekly activity, Fall 2026 weeks 1-10. Key: LMS_USER_EMAIL (no student id)' AS
WITH s AS (
  SELECT STUDENT_ID, EMAIL, TO_NUMBER(SUBSTR(STUDENT_ID, 2)) AS n, RAW.SIM_RISK(TO_NUMBER(SUBSTR(STUDENT_ID, 2))) AS r
  FROM RAW.SIS_STUDENT WHERE ENROLLMENT_STATUS = 'ACTIVE'
),
w AS (SELECT SEQ4() + 1 AS week_num FROM TABLE(GENERATOR(ROWCOUNT => 10))),
b AS (
  SELECT s.n, s.r, w.week_num,
    CASE WHEN MOD(ABS(HASH(s.n,'dom')), 100) < 3 THEN REPLACE(s.EMAIL, '@lakeside.edu', '@lakeside.com') ELSE s.EMAIL END AS e,
    GREATEST(0, ROUND(16 * (1 - 0.75 * s.r) - s.r * s.r * w.week_num * 1.3 + (MOD(ABS(HASH(s.n, w.week_num, 'lg')), 7) - 3))) AS logins,
    2 + MOD(ABS(HASH(s.n, w.week_num, 'due')), 3) AS due,
    GREATEST(0, LEAST(1, 1 - s.r * 0.9 - s.r * w.week_num / 25 + (MOD(ABS(HASH(s.n, w.week_num, 'sb')), 31) - 15) / 100.0)) AS sub_rate
  FROM s CROSS JOIN w
)
SELECT
  IFF(MOD(ABS(HASH(n,'uc')), 5) = 0, UPPER(e), e) AS LMS_USER_EMAIL,
  'Fall 2026' AS TERM, week_num AS WEEK_NUM,
  logins AS LOGINS,
  logins * (15 + MOD(ABS(HASH(n, week_num, 'mn')), 31)) AS MINUTES_ACTIVE,
  due AS ASSIGNMENTS_DUE,
  LEAST(due, ROUND(due * sub_rate)) AS ASSIGNMENTS_SUBMITTED,
  ROUND(GREATEST(35, LEAST(100, 92 - r * 45 + (MOD(ABS(HASH(n, week_num, 'sc')), 17) - 8))), 1) AS AVG_SCORE_PCT,
  GREATEST(0, ROUND(3 * (1 - r) + (MOD(ABS(HASH(n, week_num, 'dp')), 3) - 1))) AS DISCUSSION_POSTS
FROM b
UNION ALL
SELECT 'test.account' || SEQ4() || '@lakeside.edu', 'Fall 2026', 1, 1, 5, 1, 1, 100, 0
FROM TABLE(GENERATOR(ROWCOUNT => 25));
SELECT COUNT(*) AS ROWS_, COUNT(DISTINCT LOWER(LMS_USER_EMAIL)) AS DISTINCT_LMS_USERS FROM RAW.LMS_ACTIVITY;
""")

n.md("### 5c. Financial Aid and Bursar (Financial Aid Office, Student Accounts)")
n.sql("load_finaid_bursar", "Financial Aid + Bursar", """
CREATE OR REPLACE TABLE RAW.FINAID_AWARD
COMMENT = 'Financial Aid 2026-27. Keys: AID_ID (FA-nnnnnn) and bare STUDENT_NUMBER. ~85% of students have a record' AS
WITH s AS (
  SELECT STUDENT_ID, RESIDENCY, TO_NUMBER(SUBSTR(STUDENT_ID, 2)) AS n, RAW.SIM_RISK(TO_NUMBER(SUBSTR(STUDENT_ID, 2))) AS r
  FROM RAW.SIS_STUDENT
)
SELECT
  'FA-' || (100000 + n * 7) AS AID_ID,
  n AS STUDENT_NUMBER,
  '2026-27' AS AID_YEAR,
  IFF(RESIDENCY = 'In-State', 34000, 46000) AS COST_OF_ATTENDANCE,
  ROUND(IFF(RESIDENCY = 'In-State', 14000, 18000) * (1 - 0.6 * r) + MOD(ABS(HASH(n,'g')), 3000), -2) AS GRANTS_AND_SCHOLARSHIPS,
  ROUND(5500 * (0.4 + r) , -2) AS LOANS,
  IFF(MOD(ABS(HASH(n,'ws')), 100) < 30, 2400, 0) AS WORK_STUDY,
  ROUND(GREATEST(0, r * r * 16000 + (MOD(ABS(HASH(n,'un')), 3001) - 1500)), -1) AS UNMET_NEED,
  IFF(r > 0.25 AND MOD(ABS(HASH(n,'pell')), 100) < 45, 'Y', 'N') AS PELL_ELIGIBLE,
  CASE WHEN r > 0.93 THEN 'SUSPENDED' WHEN r > 0.8 THEN 'WARNING' ELSE 'MEETING' END AS SAP_STATUS
FROM s
WHERE MOD(ABS(HASH(n,'fa')), 100) < 85;

CREATE OR REPLACE TABLE RAW.BURSAR_ACCOUNT
COMMENT = 'Student Accounts. Key: STUDENT_ID (same format as SIS)' AS
WITH s AS (
  SELECT STUDENT_ID, TO_NUMBER(SUBSTR(STUDENT_ID, 2)) AS n, RAW.SIM_RISK(TO_NUMBER(SUBSTR(STUDENT_ID, 2))) AS r FROM RAW.SIS_STUDENT
),
b AS (
  SELECT STUDENT_ID, n, r,
    IFF(r > 0.5, ROUND((r - 0.45) * 9000 + (MOD(ABS(HASH(n,'bal')), 801) - 400), 2), 0) AS bal
  FROM s
)
SELECT
  'B' || LPAD(n, 7, '0') AS ACCOUNT_NO,
  STUDENT_ID,
  GREATEST(bal, 0) AS BALANCE_DUE,
  IFF(bal > 0, 10 + MOD(ABS(HASH(n,'dpd')), 111), 0) AS DAYS_PAST_DUE,
  IFF(MOD(ABS(HASH(n,'pp')), 100) < 25, 'Y', 'N') AS PAYMENT_PLAN_FLAG,
  CASE WHEN bal > 2500 AND MOD(ABS(HASH(n,'dpd')), 111) + 10 > 45 THEN 'REGISTRATION_HOLD'
       WHEN bal > 0 AND MOD(ABS(HASH(n,'dpd')), 111) + 10 > 30 THEN 'FINANCIAL_HOLD' ELSE 'NONE' END AS HOLD_TYPE
FROM b;
SELECT (SELECT COUNT(*) FROM RAW.FINAID_AWARD) AS FINAID_ROWS, (SELECT COUNT(*) FROM RAW.BURSAR_ACCOUNT) AS BURSAR_ROWS,
       (SELECT COUNT_IF(HOLD_TYPE <> 'NONE') FROM RAW.BURSAR_ACCOUNT) AS STUDENTS_WITH_HOLDS;
""")

n.md("""### 5d. Advising CRM - contacts and **free-text notes** (Advising Center)

🔹 This is the *unstructured* source. Notes contain real-world PII (phone numbers, personal emails) that must **never** reach an AI agent unredacted - we deal with that in Notebook 01 (`AI_REDACT`) and Notebook 03 (governance).""")
n.sql("load_crm", "Advising CRM", """
CREATE OR REPLACE TABLE RAW.ADVISING_CONTACT
COMMENT = 'Advising CRM contact record. Keys: CRM_CONTACT_ID (C-n) and STUDENT_REF (STU-nnnnnnn)' AS
SELECT
  'C-' || TO_NUMBER(SUBSTR(STUDENT_ID, 2)) AS CRM_CONTACT_ID,
  'STU-' || SUBSTR(STUDENT_ID, 2)          AS STUDENT_REF,
  GET(ARRAY_CONSTRUCT('Dana Whitfield','Marcus Lee','Priya Raman','Tom Alvarez','Keisha Brown','Sam Okoye','Laura Chen','Victor Ramos'),
      MOD(ABS(HASH(STUDENT_ID,'adv')), 8))::STRING AS ASSIGNED_ADVISOR
FROM RAW.SIS_STUDENT;

CREATE OR REPLACE TABLE RAW.ADVISING_NOTE
COMMENT = 'Advising CRM free-text notes. Contains PII - do NOT expose to AI without redaction' AS
WITH s AS (
  SELECT st.STUDENT_ID, st.FIRST_NAME, TO_NUMBER(SUBSTR(st.STUDENT_ID, 2)) AS n,
         RAW.SIM_RISK(TO_NUMBER(SUBSTR(st.STUDENT_ID, 2))) AS r, c.CRM_CONTACT_ID, c.ASSIGNED_ADVISOR
  FROM RAW.SIS_STUDENT st JOIN RAW.ADVISING_CONTACT c ON c.STUDENT_REF = 'STU-' || SUBSTR(st.STUDENT_ID, 2)
),
k AS (SELECT SEQ4() + 1 AS k FROM TABLE(GENERATOR(ROWCOUNT => 3))),
x AS (
  SELECT s.*, k.k,
    (s.r + (MOD(ABS(HASH(s.n, k.k, 'cn')), 41) - 20) / 100.0) > 0.62 AS concerned,
    MOD(ABS(HASH(s.n, k.k, 'tp')), 4) AS tp
  FROM s CROSS JOIN k
  WHERE MOD(ABS(HASH(s.n, k.k, 'has')), 100) < IFF(s.r > 0.6, 70, 40)
),
t AS (
  SELECT x.*,
    CASE WHEN concerned THEN GET(ARRAY_CONSTRUCT('Financial','Wellbeing','Academic','Retention'), tp)::STRING
         ELSE GET(ARRAY_CONSTRUCT('Career','Planning','Planning','Career'), tp)::STRING END AS note_type,
    CASE WHEN concerned THEN GET(ARRAY_CONSTRUCT(
      'Met with {fn} about a growing balance and a pending registration hold. Student shared that hours at their off-campus job were cut and they are unsure they can afford spring tuition. Referred to Financial Aid for a payment plan review.',
      '{fn} reported feeling overwhelmed and has been missing classes. Mentioned trouble sleeping and homesickness. Recommended campus counseling services and scheduled a follow-up check-in in two weeks.',
      'Midterm grades in two courses are below a C. {fn} says the pace of the lab sections is hard to keep up with and has not attended tutoring. Discussed a reduced course load and the withdrawal deadline.',
      '{fn} is considering transferring or stopping out after this term, citing cost and a lack of connection to other students. Advised on leave-of-absence options and asked to reconnect before registration opens.'), tp)::STRING
    ELSE GET(ARRAY_CONSTRUCT(
      '{fn} is on track and exploring summer internships in their field. Reviewed the degree audit and all milestone courses are on schedule.',
      'Routine planning meeting. {fn} is registered for next term and is interested in a research assistant position.',
      '{fn} joined a student organization and attends study groups regularly. Feeling confident about the semester.',
      'Career conversation: {fn} wants to attend the spring career fair. Updated resume together and reviewed internship deadlines.'), tp)::STRING END AS tpl
  FROM x
)
SELECT
  'N' || LPAD(ROW_NUMBER() OVER (ORDER BY STUDENT_ID, k), 7, '0') AS NOTE_ID,
  CRM_CONTACT_ID,
  DATEADD(day, MOD(ABS(HASH(n, k, 'dt')), 70), '2026-08-24'::DATE) AS NOTE_DATE,
  ASSIGNED_ADVISOR AS ADVISOR_NAME,
  note_type AS NOTE_TYPE,
  REPLACE(tpl, '{fn}', FIRST_NAME)
    || IFF(MOD(ABS(HASH(n, k, 'ph')), 100) < 25, ' Student can be reached at 555-' || LPAD(MOD(ABS(HASH(n,'ph')), 10000), 4, '0') || '.', '')
    || IFF(MOD(ABS(HASH(n, k, 'em')), 100) < 15, ' Prefers contact via personal email ' || LOWER(FIRST_NAME) || n || '@gmail.com.', '') AS NOTE_TEXT
FROM t;
SELECT COUNT(*) AS NOTES, COUNT_IF(NOTE_TEXT ILIKE '%@gmail.com%' OR NOTE_TEXT LIKE '%555-%') AS NOTES_WITH_PII FROM RAW.ADVISING_NOTE;
""")

n.md("### 5e. Campus ID card swipes (Campus Card Office)\n\n🔹 Joined to students **only by email** via the card roster.")
n.sql("load_campus", "Campus engagement", """
CREATE OR REPLACE TABLE RAW.ID_CARD_ROSTER
COMMENT = 'Campus card roster. Keys: CARD_ID and EMAIL (no student id)' AS
SELECT 'CARD' || LPAD(10000 + TO_NUMBER(SUBSTR(STUDENT_ID, 2)) * 3, 7, '0') AS CARD_ID,
       EMAIL, '2026-08-15'::DATE AS ISSUED_DATE
FROM RAW.SIS_STUDENT;

CREATE OR REPLACE TABLE RAW.CAMPUS_ENGAGEMENT
COMMENT = 'Campus card swipes by week, Fall 2026 weeks 1-10. Key: CARD_ID' AS
WITH s AS (
  SELECT r.CARD_ID, TO_NUMBER(SUBSTR(st.STUDENT_ID, 2)) AS n, RAW.SIM_RISK(TO_NUMBER(SUBSTR(st.STUDENT_ID, 2))) AS rk
  FROM RAW.SIS_STUDENT st JOIN RAW.ID_CARD_ROSTER r ON r.EMAIL = st.EMAIL WHERE st.ENROLLMENT_STATUS = 'ACTIVE'
),
w AS (SELECT SEQ4() + 1 AS week_num FROM TABLE(GENERATOR(ROWCOUNT => 10)))
SELECT CARD_ID, 'Fall 2026' AS TERM, week_num AS WEEK_NUM,
  GREATEST(0, ROUND(5 * (1 - rk) - rk * week_num / 6 + (MOD(ABS(HASH(n, week_num, 'lb')), 4) - 1.5))) AS LIBRARY_VISITS,
  GREATEST(0, ROUND(3 * (1 - rk) + (MOD(ABS(HASH(n, week_num, 'rc')), 4) - 1.5))) AS REC_CENTER_VISITS,
  GREATEST(0, ROUND(10 * (1 - 0.5 * rk) + (MOD(ABS(HASH(n, week_num, 'dn')), 5) - 2))) AS DINING_SWIPES,
  GREATEST(0, ROUND(1.5 * (1 - rk) + (MOD(ABS(HASH(n, week_num, 'ev')), 3) - 1))) AS EVENTS_ATTENDED
FROM s CROSS JOIN w;
SELECT COUNT(*) AS ROWS_ FROM RAW.CAMPUS_ENGAGEMENT;
""")

n.md("## Step 6: Validate")
n.sql("validate_raw", "Validate raw sources", """
SELECT 'SIS_STUDENT' AS SRC, COUNT(*) AS ROWS_ FROM RAW.SIS_STUDENT
UNION ALL SELECT 'SIS_ENROLLMENT', COUNT(*) FROM RAW.SIS_ENROLLMENT
UNION ALL SELECT 'LMS_ACTIVITY', COUNT(*) FROM RAW.LMS_ACTIVITY
UNION ALL SELECT 'FINAID_AWARD', COUNT(*) FROM RAW.FINAID_AWARD
UNION ALL SELECT 'BURSAR_ACCOUNT', COUNT(*) FROM RAW.BURSAR_ACCOUNT
UNION ALL SELECT 'ADVISING_CONTACT', COUNT(*) FROM RAW.ADVISING_CONTACT
UNION ALL SELECT 'ADVISING_NOTE', COUNT(*) FROM RAW.ADVISING_NOTE
UNION ALL SELECT 'ID_CARD_ROSTER', COUNT(*) FROM RAW.ID_CARD_ROSTER
UNION ALL SELECT 'CAMPUS_ENGAGEMENT', COUNT(*) FROM RAW.CAMPUS_ENGAGEMENT;
""")
n.md("""### 🛠️ Try it - see the identity problem for yourself

Run the query below. Every source calls the same student something different.""")
n.sql("see_keys", "Same student, six keys", """
SELECT s.STUDENT_ID AS SIS_KEY,
       MAX(l.LMS_USER_EMAIL) AS LMS_KEY,
       MAX(f.AID_ID)         AS FINAID_KEY,
       MAX(c.CRM_CONTACT_ID) AS CRM_KEY,
       MAX(r.CARD_ID)        AS CARD_KEY,
       MAX(b.ACCOUNT_NO)     AS BURSAR_KEY
FROM RAW.SIS_STUDENT s
LEFT JOIN RAW.LMS_ACTIVITY l   ON LOWER(l.LMS_USER_EMAIL) = s.EMAIL
LEFT JOIN RAW.FINAID_AWARD f   ON f.STUDENT_NUMBER = 42
LEFT JOIN RAW.ADVISING_CONTACT c ON c.STUDENT_REF = 'STU-0000042'
LEFT JOIN RAW.ID_CARD_ROSTER r ON r.EMAIL = s.EMAIL
LEFT JOIN RAW.BURSAR_ACCOUNT b ON b.STUDENT_ID = s.STUDENT_ID
WHERE s.STUDENT_ID = 'S0000042'
GROUP BY s.STUDENT_ID;
""")

n.footer([
    f"Role `{ROLE}`, database `{DB}` with RAW / CURATED / GOVERNANCE / SEMANTIC / AGENTS schemas, XS warehouse `{WH}`",
    "Six simulated source systems in `RAW`, each with a different student key format",
    "Cross-region inference enabled",
],
    [
        "Everything lives under one database + role, so the lab is isolated on a shared account and trivially removable (Notebook 07).",
        "The data is deterministic and synthetic - safe to share, identical for every attendee.",
        "Real campuses never share one student key. Identity resolution is the first job of a Student 360.",
    ],
    "**Notebook 01** - resolve identities and build the Student 360 with dynamic tables and Cortex AI functions.")
n.write()
