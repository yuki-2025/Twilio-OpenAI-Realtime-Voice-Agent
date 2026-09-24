
## 2. Development Workflow (IMPORTANT)
- **Respond to the user in Chinese.** Write all code, identifiers, and code comments in English. Write the plan in chinese too.
 - **Ongoing conversation work, bug fixes, small edits, refactors** → just do it.
- **New module or new feature** → always plan first:
  1. Write the plan to a **new file** at `docs/PLAN_<MMDD>_<topic>.md`, where:
     - `<MMDD>` = today's date, 2-digit month + 2-digit day, no separator (Aug 8 → `0808`, Dec 15 → `1215`).
     - `<topic>` = short lowercase topic name, words joined by `_` (e.g. `elevenlabs_latency`).
     - Full example: `docs/PLAN_0808_elevenlabs_latency.md`.
     - No fixed section headers required. Briefly cover: 需求 (requirement), 现状 (current state), and the solution overview + key decisions.
     - Then detail the solution — include whatever's needed (step-by-step, files to touch, risks, etc.), only what's relevant.
     - If the workload is large: first briefly state **Target & Solution** (goal + solution in 1-2 sentences), then split the implementation into **phases**, with details under each phase.
  2. Show the plan to the user and stop. Wait for an explicit approval message.
  3. Only after approval, write code.
  - Do **not** modify the codebase for a new feature/module before approval.
- when prepare to commit, do not write Co-Authored-By: Claude and prepare to commit.
- once new function development is done, add a changelog entry to `README.md`: include the date, bump the version (x.x), and briefly explain the function(s) added. Example:
  ```
  ## v2.3 Main title- 7/4/2025
  - function1: brief explanation of what changed and why
  - function2: brief explanation of what changed and why
  ```
