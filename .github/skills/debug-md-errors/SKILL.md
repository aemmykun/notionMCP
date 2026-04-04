---
name: debug-md-errors
description: 'Debug markdownlint and markdown style errors in Markdown files. Use for MD022, MD032, MD036, MD060, heading spacing, list spacing, emphasis-as-heading, and table pipe spacing fixes.'
argument-hint: 'Provide file path, error codes, and whether to auto-fix only formatting-safe issues.'
---

# Debug Markdown Errors

## Outcome
Produce a clean, lint-compliant Markdown file by fixing structural spacing and style issues without changing document meaning.

## When To Use
- You see markdownlint warnings or errors in a Markdown file.
- You need fast triage for repeated style violations.
- You want deterministic fixes with explicit validation gates.

## Inputs To Collect
- Target file path.
- Error list with line numbers and rule codes.
- Whether content changes are allowed, or only formatting-safe edits.

## Procedure
1. Group findings by rule code.
2. Apply safe bulk fixes for spacing rules first.
3. Apply table normalization fixes.
4. Resolve semantic style rules that need judgment.
5. Re-run lint and confirm zero target-rule findings.

## Rule-by-Rule Playbook

### MD022: blanks-around-headings
- Ensure one blank line before each heading, except at top of file.
- Ensure one blank line after each heading before paragraphs, lists, or tables.
- Keep fenced code blocks intact and do not insert blank lines inside fences.

### MD032: blanks-around-lists
- Ensure one blank line before a list when it follows regular paragraph text.
- Ensure one blank line after a list before the next heading or paragraph.
- Do not add blank lines between list items unless using loose-list style intentionally.

### MD060: table-column-style (compact)
- Normalize pipes to compact style with surrounding spaces per column cell.
- Keep header separator row aligned and valid.
- Preserve table content and column count.

### MD036: no-emphasis-as-heading
- Replace emphasis-only heading-like lines with a real heading token.
- Convert patterns like `**Title**` into `### Title` using nearest heading depth.
- Keep section hierarchy consistent with surrounding headings.

## Decision Points
- If a change can alter meaning, pause and ask for user preference.
- If line references appear stale after edits, re-scan by rule pattern instead of trusting old line numbers.
- If the file mixes intentional nonstandard style, ask whether to keep local style or enforce linter default.

## Validation Checklist
- Linter rerun shows no remaining findings for requested rules.
- No table row lost columns after normalization.
- Heading hierarchy remains logical.
- Diff contains only formatting and heading-token adjustments, not semantic rewrites.

## Example Invocation Prompts
- Debug markdownlint errors in FREEZE_SNAPSHOT.md for MD022 and MD032.
- Fix all MD060 compact table spacing warnings in docs.
- Convert emphasis-style headings to real headings and re-validate.

## Completion Criteria
- Target file passes lint for requested rules.
- User confirms no unintended content meaning changed.
