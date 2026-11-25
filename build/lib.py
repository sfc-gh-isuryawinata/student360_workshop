import json, uuid, os, hashlib

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "notebooks")
DB = "STUDENT360_LAB"
ROLE = "STUDENT360_LAB_ADMIN"
WH = "STUDENT360_LAB_WH"

def uid(seed):
    return hashlib.md5(seed.encode()).hexdigest()[:8]

class NB:
    def __init__(self, fname, num, title, phase, minutes):
        self.fname, self.num, self.title, self.phase, self.minutes = fname, num, title, phase, minutes
        self.cells = []

    def md(self, text):
        self.cells.append({"cell_type": "markdown", "id": uid(self.fname + str(len(self.cells))),
                           "metadata": {"codeCollapsed": True}, "source": text.strip("\n")})

    def sql(self, name, title, src):
        self.cells.append({"cell_type": "code", "id": uid(self.fname + str(len(self.cells))),
                           "execution_count": None,
                           "metadata": {"language": "sql", "name": name, "title": title, "resultVariableName": name},
                           "outputs": [], "source": f"%%sql -r {name}\n" + src.strip("\n")})

    def header(self, does, why, prereq):
        lines = "\n".join(f"{i}. {d}" for i, d in enumerate(does, 1))
        self.md(f"""# Student 360 Workshop - {self.title}
## Notebook {self.num:02d} ({self.phase})

_Icons: 🛠️ Action  📌 Note  🔹 Info  🎓 Higher-ed context  ✅ Best practice_

---
### What this notebook does
{lines}

### Why it matters
{why}

**Estimated time:** {self.minutes} min  |  **Prerequisite:** {prereq}
""")

    def footer(self, built, points, nxt):
        b = "\n".join(f"- {x}" for x in built)
        p = "\n".join(f"- {x}" for x in points)
        self.md(f"""## ✅ Notebook {self.num:02d} complete

### What you just built
{b}

---
### Key points
{p}

---
### Next
{nxt}
""")

    def write(self):
        nb = {"cells": [], "metadata": {"kernelspec": {"display_name": "SQL", "language": "sql", "name": "sql"},
                                         "language_info": {"name": "sql"}}, "nbformat": 4, "nbformat_minor": 5}
        for c in self.cells:
            c = dict(c)
            if c["cell_type"] == "markdown":
                c["metadata"] = {"codeCollapsed": True}
            nb["cells"].append(c)
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, self.fname), "w") as f:
            json.dump(nb, f, indent=1)
        print("wrote", self.fname, len(self.cells), "cells")
