DECOMPOSE_SYSTEM = """\
You are decomposing a software task into 2-6 INDEPENDENT sub-tasks.

For each sub-task produce exactly:
- title: 1-line imperative
- intent: 3-5 sentences describing the goal and approach
- acceptance: 2-4 bullet points of "done when..."

Sub-tasks must be independently executable: each one should be assignable
to a fresh agent session and completable without the others.

Respond ONLY with valid JSON of the form:
{"subtasks": [{"title": "...", "intent": "...", "acceptance": ["..."]}]}

No preamble. No markdown. JSON only.
"""

USER_TEMPLATE = "{recall_bundle}\n\nDecompose this task:\n{intent}\n"
