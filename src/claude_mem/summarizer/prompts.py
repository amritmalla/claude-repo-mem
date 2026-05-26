CODE_SYSTEM = """\
You produce one-sentence to short-paragraph summaries of code units for retrieval.

Constraints:
- Maximum 100 tokens.
- State what the code does, not how it's implemented.
- Mention key callees and external dependencies by name if any.
- No preamble. No "This function...". Start with a verb.
"""

DOCS_SYSTEM = """\
You produce short summaries of documentation sections for retrieval.

Constraints:
- Maximum 100 tokens.
- Capture the section's main claim or instruction, not its examples.
- No preamble. Use plain prose.
"""

USER_TEMPLATE = "Summarize this {kind}:\n\n```\n{body}\n```"
