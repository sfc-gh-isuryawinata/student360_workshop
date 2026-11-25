from lib import NB, DB, ROLE, WH

ADV = "STUDENT360_LAB_ADVISOR_ENGINEERING"
IR = "STUDENT360_LAB_IR_ANALYST"

def agent_sql(fqn, display, color, instructions, notes_search, comment):
    return f"""
CREATE OR REPLACE AGENT {fqn}
  COMMENT = '{comment}'
  PROFILE = '{{"display_name": "{display}", "color": "{color}"}}'
  FROM SPECIFICATION
$$
models:
  orchestration: auto

orchestration:
  budget:
    seconds: 45
    tokens: 16000

instructions:
  response: |
{instructions['response']}
  orchestration: |
{instructions['orchestration']}
  sample_questions:
{instructions['samples']}

tools:
  - tool_spec:
      type: "cortex_analyst_text_to_sql"
      name: "student_analytics"
      description: "Query structured student data: students, enrollments, GPA, risk scores and drivers, financial need, holds, LMS engagement and campus activity. Use for any question about numbers, counts, rankings or lists of students."
  - tool_spec:
      type: "cortex_search"
      name: "advising_notes"
      description: "Search PII-redacted advising notes for qualitative context such as what students and advisors are reporting. Use for why questions and for themes."
  - tool_spec:
      type: "data_to_chart"
      name: "data_to_chart"
      description: "Create a chart from query results when the user asks for a visual."

tool_resources:
  student_analytics:
    semantic_view: "{DB}.SEMANTIC.STUDENT_360_SV"
    execution_environment:
      type: warehouse
      warehouse: "{WH}"
  advising_notes:
    name: "{DB}.AGENTS.{notes_search}"
    max_results: "5"
$$;
"""

ADVISOR_INSTR = {
    "response": """    You are the Advisor Assistant for Lakeside University's College of Engineering.
    You help academic advisors prioritise outreach to their students.
    - Be concise. Lead with the student's name, STUDENT_ID and the risk tier.
    - Always explain WHY a student is at risk using TOP_RISK_DRIVERS. Never give a risk score without its drivers.
    - The risk score is a triage signal for outreach. Never describe a student as certain to leave.
    - Never disclose or infer contact details, dates of birth, or protected characteristics.
    - If the question spans structured data and advising notes, use BOTH tools and cite which source each fact came from.""",
    "orchestration": """    - Numbers, rankings, lists of students, GPA, holds, LMS and campus data: use student_analytics.
    - Why a student is struggling, advisor-noted concerns, themes in conversations: use advising_notes.
    - Advisors name themselves in the question (for example "my caseload" or "Dana Whitfield's students"). Filter on ASSIGNED_ADVISOR. If no advisor name is given, ask which advisor the caseload belongs to.
    - Questions about students outside the Engineering college will not return data. Say so plainly.""",
    "samples": """    - question: "Who are the 10 students on Dana Whitfield's caseload I should reach out to first, and why?"
    - question: "Which of my students have a registration hold?"
    - question: "What are students in my college saying in advising notes about finances?\"""",
}

IR_INSTR = {
    "response": """    You are the Student Success Analyst for Lakeside University Institutional Research.
    You answer institution-wide questions about retention, academics, engagement, finances and advising.
    - Be concise and data-driven. Lead with the number, then the breakdown.
    - Show percentages with one decimal place. Show money in whole dollars.
    - Always state the population and the term you are reporting on (Fall 2026, week 10).
    - Aggregate analysis only: do not name individual students unless asked for a specific student's risk drivers.
    - Never disclose or infer contact details or dates of birth.
    - If the question spans structured data and advising notes, use BOTH tools and cite which source each fact came from.""",
    "orchestration": """    - Counts, rates, averages, rankings, comparisons across colleges, cohorts or course sections: use student_analytics.
    - Qualitative themes, what advisors are hearing, why students are struggling: use advising_notes.
    - For questions about risk drivers across the population, use student_analytics on TOP_RISK_DRIVERS.""",
    "samples": """    - question: "How many high-risk students are in each college, and what is the at-risk rate?"
    - question: "Which courses have the highest DFW rate this term?"
    - question: "What are advisors hearing from students who are considering leaving?\"""",
}

n = NB("Notebook_04_Build_Agent_Harden.ipynb", 4, "Build and Harden the AI Agents", "Phase 4 - Build the AI experience", 40)
n.header([
    "🛠️ Creates **two agents from one specification pattern** - an *Advisor Assistant* (College of Engineering only) and a *Student Success Analyst* (institution-wide) - each with a structured tool, an unstructured tool and a chart tool",
    "🛠️ Grants the **layer-2 agent permission** that completes the four-layer access model",
    "🛠️ Tests each agent **as each persona** and shows the data layer enforcing scope",
    "🛠️ Adds **cost control**: attribution tags, a warehouse statement timeout, a spending budget and a per-user quota (monitoring mode)",
],
    "An agent is a *spec*, not a prompt: tools, instructions and guardrails declared in one versioned object. Keeping it declarative means you can review it, version it and promote it - the same discipline as the data layer.",
    "Notebook 03")

n.sql("set_context", "Set Context", f"""
USE ROLE {ROLE};
USE DATABASE {DB};
USE SCHEMA AGENTS;
USE WAREHOUSE {WH};
SELECT CURRENT_ROLE(), CURRENT_SCHEMA();
""")

n.md("""## Step 1: Anatomy of an Agent Specification

🛠️ The spec below has five parts. Read them before you run the cell:

| Section | Purpose | Best practice |
|---|---|---|
| `orchestration.budget` | Caps seconds and tokens per question | Always set one - a runaway agent is a cost incident |
| `instructions.response` | *How* to answer: tone, format, citations, guardrails | Put non-negotiables here: "never disclose contact details", "a risk score is a triage signal" |
| `instructions.orchestration` | *Which tool* to use for which question | Route explicitly; vague routing is the #1 cause of wrong tool choice |
| `tools` | What the agent can call | `description` is how the model picks a tool - write it like a job description |
| `tool_resources` | Where each tool points | Point structured tools at the **semantic view**, unstructured tools at a **search service** |

✅ **Best practice - two agents, not one super-agent.** The Advisor Assistant and the Student Success Analyst share the same semantic view and tools, but the **data they can reach is different** because their roles differ (Notebook 03). Scope is enforced by the data layer, so the two agents can use the *same code*.""")

n.md("### Step 2: Create the Advisor Assistant (College of Engineering)")
n.sql("create_advisor_agent", "Create Advisor Assistant", agent_sql(
    f"{DB}.AGENTS.ADVISOR_ASSISTANT", "Advisor Assistant (Engineering)", "green", ADVISOR_INSTR,
    "ADVISING_NOTES_SEARCH_ENGINEERING",
    "Advisor Assistant for the College of Engineering - caseload prioritisation, scoped to Engineering rows and notes"))

n.md("### Step 3: Create the Student Success Analyst (institution-wide)")
n.sql("create_ir_agent", "Create Student Success Analyst", agent_sql(
    f"{DB}.AGENTS.STUDENT_SUCCESS_ANALYST", "Student Success Analyst", "blue", IR_INSTR,
    "ADVISING_NOTES_SEARCH",
    "Institutional Research assistant - institution-wide aggregate analysis, PII masked"))

n.sql("describe_agents", "Inspect the specs", f"""
DESCRIBE AGENT {DB}.AGENTS.ADVISOR_ASSISTANT;
DESCRIBE AGENT {DB}.AGENTS.STUDENT_SUCCESS_ANALYST;
""")

n.md("""## Step 4: Layer 2 - Grant `USAGE ON AGENT`

🛠️ This completes the four-layer model from Notebook 03. Until this grant exists, the consumer role can see the semantic view but **cannot invoke the agent** - a common and confusing failure in real deployments.

🔹 Notice that the Advisor Assistant is granted only to the Engineering advisor role, and the Student Success Analyst only to the IR role. Nothing else changes.""")
n.sql("grant_agents", "Grant agent usage", f"""
USE ROLE ACCOUNTADMIN;
GRANT USAGE ON AGENT {DB}.AGENTS.ADVISOR_ASSISTANT          TO ROLE {ADV};
GRANT USAGE ON AGENT {DB}.AGENTS.STUDENT_SUCCESS_ANALYST    TO ROLE {IR};
USE ROLE {ROLE};
SELECT 'USAGE ON AGENT granted (layer 2)' AS STATUS;
""")

n.md("""## Step 5: Test Each Agent as Each Persona

🛠️ Same question, different persona, different answer. Every call goes through `SNOWFLAKE.CORTEX.DATA_AGENT_RUN`, the same API that CoWork and custom apps use, so this is the real path.

> 🔹 `DATA_AGENT_RUN` returns the agent's full event stream (thinking, tool calls, tool results, final text). The final answer is the item with `type = 'text'`.""")
n.sql("test_advisor_agent", "Advisor Assistant - Engineering advisor", f"""
USE ROLE {ADV};
USE SECONDARY ROLES NONE;
USE WAREHOUSE {WH};
SELECT TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
  '{DB}.AGENTS.ADVISOR_ASSISTANT',
  $${{"messages": [{{"role": "user", "content": [{{"type": "text", "text": "I am advisor Dana Whitfield. Who are the 5 students on my caseload I should reach out to first, and why?"}}]}}], "stream": false}}$$
)) AS RESP;
""")
n.sql("test_ir_agent", "Student Success Analyst - IR analyst", f"""
USE ROLE {IR};
USE SECONDARY ROLES NONE;
USE WAREHOUSE {WH};
SELECT TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
  '{DB}.AGENTS.STUDENT_SUCCESS_ANALYST',
  $${{"messages": [{{"role": "user", "content": [{{"type": "text", "text": "How many high-risk students are in each college, and what is the at-risk rate?"}}]}}], "stream": false}}$$
)) AS RESP;
""")
n.sql("test_guardrail", "Guardrail: contact details refused", f"""
USE ROLE {IR};
USE SECONDARY ROLES NONE;
USE WAREHOUSE {WH};
SELECT TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
  '{DB}.AGENTS.STUDENT_SUCCESS_ANALYST',
  $${{"messages": [{{"role": "user", "content": [{{"type": "text", "text": "What is the email address and phone number of Maria Garcia?"}}]}}], "stream": false}}$$
)) AS RESP;
""")
n.sql("test_no_access", "Negative test: advisor cannot call the IR agent", f"""
USE ROLE {ADV};
USE SECONDARY ROLES NONE;
USE WAREHOUSE {WH};
-- Expect: error 399513 - agent does not exist or access is not authorized (layer 2 is missing for this role)
SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
  '{DB}.AGENTS.STUDENT_SUCCESS_ANALYST',
  $${{"messages": [{{"role": "user", "content": [{{"type": "text", "text": "How many students are there?"}}]}}], "stream": false}}$$
);
""")

n.md("""## Step 6: Cost Control - Observe, Attribute, Constrain

🛠️ The reference pattern for AI spend is **Observe → Attribute → Control**. Each step is a different Snowflake primitive:

| Step | Primitive | What it answers |
|---|---|---|
| **Observe** | `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY` | Which agent, which user, how many tokens, how many credits |
| **Attribute** | A `TAG` on the agents and warehouse | Which department to charge |
| **Control** | Warehouse statement timeout, a **budget** with a spending limit and notification threshold, a **per-user quota** | Hard limits before a surprise invoice |""")
n.sql("observe_agents", "Observe agent usage", f"""
SELECT START_TIME, USER_NAME, AGENT_NAME, TOKENS, TOKEN_CREDITS
FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
WHERE AGENT_NAME IN ('ADVISOR_ASSISTANT', 'STUDENT_SUCCESS_ANALYST')
ORDER BY START_TIME DESC
LIMIT 20;
""")
n.sql("create_tag", "Cost-centre tag", f"""
CREATE TAG IF NOT EXISTS {DB}.AGENTS.COST_CENTER
  ALLOWED_VALUES 'student-success', 'advising', 'institutional-research'
  COMMENT = 'Cost-centre attribution for AI and warehouse spend';
ALTER AGENT {DB}.AGENTS.ADVISOR_ASSISTANT       SET TAG {DB}.AGENTS.COST_CENTER = 'advising';
ALTER AGENT {DB}.AGENTS.STUDENT_SUCCESS_ANALYST SET TAG {DB}.AGENTS.COST_CENTER = 'institutional-research';
ALTER WAREHOUSE {WH} SET TAG {DB}.AGENTS.COST_CENTER = 'student-success';
SHOW TAGS IN SCHEMA {DB}.AGENTS;
""")
n.sql("harden_warehouse", "Warehouse statement timeout", f"""
USE ROLE ACCOUNTADMIN;
ALTER WAREHOUSE {WH} SET STATEMENT_TIMEOUT_IN_SECONDS = 300;
SHOW WAREHOUSES LIKE '{WH}';
""")
n.sql("create_budget", "Spending budget with alert", f"""
USE ROLE {ROLE};
CREATE OR REPLACE SNOWFLAKE.CORE.BUDGET {DB}.AGENTS.AI_BUDGET();
CALL {DB}.AGENTS.AI_BUDGET!SET_SPENDING_LIMIT(50);
CALL {DB}.AGENTS.AI_BUDGET!SET_NOTIFICATION_THRESHOLD(75);
CALL {DB}.AGENTS.AI_BUDGET!GET_SPENDING_LIMIT();
""")
n.sql("create_quota", "Per-user quota (monitoring mode)", f"""
USE ROLE ACCOUNTADMIN;
CREATE OR REPLACE SNOWFLAKE.CORE.QUOTA {DB}.AGENTS.AI_USER_QUOTA();
CALL {DB}.AGENTS.AI_USER_QUOTA!ADD_SHARED_RESOURCE('CORTEX AGENT', (SELECT SYSTEM$REFERENCE('CORTEX AGENT', '{DB}.AGENTS.ADVISOR_ASSISTANT')));
CALL {DB}.AGENTS.AI_USER_QUOTA!ADD_SHARED_RESOURCE('CORTEX AGENT', (SELECT SYSTEM$REFERENCE('CORTEX AGENT', '{DB}.AGENTS.STUDENT_SUCCESS_ANALYST')));
CALL {DB}.AGENTS.AI_USER_QUOTA!SET_PER_USER_LIMIT(50);
CALL {DB}.AGENTS.AI_USER_QUOTA!GET_CONFIG();
""")

n.md("""### 🔹 Why monitoring mode for the quota

The quota in this workshop is **created in monitoring mode** - it records and reports usage, but it does not block anyone or send emails. That keeps the lab safe to run in a shared account. In production, set a per-user daily limit and enforcement; the call is the same with an extra enforcement parameter.""")

n.md("""## 🧠 What You Just Built

| Control | Layer | Where |
|---|---|---|
| Two agents, each scoped by role | Access (layer 2) | Step 4-5 |
| Guardrail: contact details refused, adverse action refused | Instructions + `AI_QUESTION_CATEGORIZATION` | Step 5 |
| Budget per agent (tokens + seconds) | Orchestration | Step 2-3 |
| Attribution tags | Cost | Step 6 |
| Warehouse timeout | Cost | Step 6 |
| Spending budget with alert | Cost | Step 6 |
| Per-user quota | Cost | Step 6 |""")

n.footer([
    f"Agents `{DB}.AGENTS.ADVISOR_ASSISTANT` (Engineering) and `{DB}.AGENTS.STUDENT_SUCCESS_ANALYST` (institution-wide)",
    "Layer-2 `USAGE ON AGENT` grants to each persona's role",
    "Cost attribution tags, a warehouse statement timeout, a spending budget and a per-user quota (monitoring mode)",
],
    [
        "An agent is a versioned spec: instructions, tools and budgets in one object.",
        "Same code, different persona: the data layer decides what each agent can answer.",
        "Observe, attribute, control - AI spend needs the same discipline as compute.",
    ],
    "**Notebook 05** - evaluate the agents with a scored gate and publish them to CoWork.")
n.write()
