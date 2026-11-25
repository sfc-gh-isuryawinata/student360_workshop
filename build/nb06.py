from lib import NB, DB, ROLE, WH

ADV = "STUDENT360_LAB_ADVISOR_ENGINEERING"
IR = "STUDENT360_LAB_IR_ANALYST"

n = NB("Notebook_06_Cleanup.ipynb", 6, "Cleanup", "Clean up", 5)
n.header([
    "🛠️ **Unpublishes** the lab's agents from the shared CoWork object",
    "🛠️ Removes the **budget, quota and cost tags** created in Notebook 04",
    "🛠️ Drops the **database, warehouse and roles** - everything the lab created",
    "🛠️ **Verifies** the account is clean and the shared CoWork object is intact",
],
    "A workshop that leaves objects behind costs money and confuses the next team. Cleanup is the last lesson in the lifecycle: remove only what you created, and prove it.",
    "Any of Notebooks 00-05 (run this when you are finished)")

n.md("""> ⚠️ This notebook removes **only** the `STUDENT360_LAB` objects. Do not run it in an account where you need the Student 360 data afterwards.""")

n.sql("set_context", "Set Context", f"""
USE ROLE ACCOUNTADMIN;
SELECT CURRENT_ROLE();
""")

n.md("## Step 1: Unpublish the Agents from CoWork")
n.md("🛠️ Only the lab's agents are removed. The shared CoWork object itself, and any agents other teams have published to it, are untouched.")
n.sql("unpublish", "Remove lab agents from CoWork", f"""
USE ROLE ACCOUNTADMIN;
ALTER SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT DROP AGENT {DB}.AGENTS.ADVISOR_ASSISTANT;
ALTER SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT DROP AGENT {DB}.AGENTS.STUDENT_SUCCESS_ANALYST;
""")

n.md("## Step 2: Remove the Persona Grant from Your User")
n.sql("revoke_me", "Revoke persona roles from current user", f"""
USE ROLE ACCOUNTADMIN;
SET ME = CURRENT_USER();
REVOKE ROLE {ADV} FROM USER IDENTIFIER($ME);
REVOKE ROLE {IR}  FROM USER IDENTIFIER($ME);
""")

n.md("## Step 3: Drop the Budget, Quota and Tags")
n.sql("drop_cost_objects", "Drop budget, quota, tags", f"""
USE ROLE {ROLE};
DROP SNOWFLAKE.CORE.BUDGET IF EXISTS {DB}.AGENTS.AI_BUDGET;
USE ROLE ACCOUNTADMIN;
DROP SNOWFLAKE.CORE.QUOTA IF EXISTS {DB}.AGENTS.AI_USER_QUOTA;
""")

n.md("## Step 4: Drop the Database, Warehouse and Roles")
n.md("🔹 Dropping the database removes the agents, semantic view, search services, dynamic tables, policies, eval dataset and stage in one step.")
n.sql("drop_database", "Drop database and warehouse", f"""
USE ROLE ACCOUNTADMIN;
DROP DATABASE IF EXISTS {DB};
DROP WAREHOUSE IF EXISTS {WH};
""")
n.sql("drop_roles", "Drop lab roles", f"""
USE ROLE ACCOUNTADMIN;
DROP ROLE IF EXISTS {ADV};
DROP ROLE IF EXISTS {IR};
DROP ROLE IF EXISTS {ROLE};
""")

n.md("## Step 5: Verify a Clean Account")
n.sql("verify_clean", "Verify clean", f"""
USE ROLE ACCOUNTADMIN;
SHOW DATABASES LIKE 'STUDENT360_LAB';
SHOW WAREHOUSES LIKE 'STUDENT360_LAB%';
SHOW ROLES LIKE 'STUDENT360_LAB%';
SHOW AGENTS IN SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT;
""")

n.md("""📌 **Expected:** the first three commands return no rows. The last command still lists any agents other teams published to the shared CoWork object - that is correct, and it is exactly why we only removed our own.

## ✅ Notebook 06 complete

### What you just did
- Removed the lab's agents from the shared CoWork object
- Dropped the budget, quota, tags, database, warehouse and roles
- Verified that nothing from the lab remains and the shared object is intact

---
### Key points
- Clean up is part of the lifecycle, not an afterthought.
- Remove only what you created: shared objects stay shared.
- Drop the database and everything under it goes with it, which is why one namespace per lab matters.

---
### Thank you
You have built a Student 360 for higher education from six siloed sources, given it meaning, governed it, and put an AI assistant on top that respects who is asking.
""")
n.write()
