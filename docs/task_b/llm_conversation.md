# Task B/C – LLM conversation for the generated code

The prototype code, tests, README and these documents were **generated completely** by
Claude Opus 5.5 (`claude-opus-5-5`, Anthropic) in one claude.ai session on 25–26 Oct 2026

## 1 Initial request (student)

> *[Attached: system description, G20Lab2.pdf, Assignment 3 text]*
> do assignment 3 in python. Use IMGUI to do the UI for the smart fridge, do an interview first to
> ask me what I want then build it

## 2 Interview (LLM questions → student answers)

| # | Question asked by the LLM | Answer |
|---|---|---|
| 1 | You wrote "smart fridge", but the lab system is the SmartBrew AI coffee machine. Which should the prototype be? | SmartBrew coffee |
| 2 | Which Python immediate-mode GUI library? (imgui-bundle / pyimgui + glfw / Dear PyGui) | imgui-bundle |
| 3 | How much of Assignment 3 should be produced? | Everything (Task A docs + transcript + comparison, Task B code, Task C README/comments) |
| 4 | How should camera mood detection work? (simulated / real webcam + OpenCV / skip) | Simulated |
| 5 | Which 10 features? (proposed set / swap in LLM ordering / swap in offline fallback) | Proposed 10: accounts + NFC, browse + nutrition, customise, depleted blocking, payments, transaction log, saved recipes, recommendations, simulated mood, admin mode |
| 6 | Storage? (SQLite / JSON) | SQLite |
| 7 | Target OS? | Cross-platform |
| 8 | Format of Task A documents? | Markdown in the repository |

## 3 How the LLM built it (summary of its steps)

1. Tried to install `imgui-bundle` in its sandbox; the sandbox had no access to PyPI, so it wrote
   the GUI against the documented imgui-bundle API and verified it with a fake `imgui` module
   (tests/fake_imgui.py) instead of a real window.
2. Wrote the GUI-free core first: SQLite schema and seed data (`db.py`), security helpers, catalogue
   and customisation maths, inventory and bins, accounts, recipes, transactions, payments,
   weather, recommender, mood detector, admin gate and the `SmartBrewMachine` facade.
3. Wrote `tests/test_features.py` (one class per feature) — **33 tests passed on the first run**.
4. Wrote the immediate-mode GUI (`smartbrew/ui/theme.py`, `smartbrew/ui/app.py`) and the headless
   UI journeys (`tests/test_ui_smoke.py`) — **39/39 tests pass** in total.
5. Ran the Task A elicitation with the staged prompts in `docs/task_a/01_prompt_strategy_and_transcript.md`.
6. Wrote the README with setup, run and test instructions for the 10 features.

## 4 Student review responsibilities

Because the code is LLM-generated, the group should, before submitting:

- run `python main.py` on a real machine and click through the 10 demos in the README;
- read the comparison document and adjust the accept/reject decisions to the group's own opinion;
- add the claude.ai share link above.
