---
name: grading-review
description: This skill should be used when reviewing student submissions, applying rubrics, drafting feedback, checking grading consistency, or preparing grade publication actions that require approval.
---

# Grading Review Skill

## Purpose

Provide a repeatable workflow for rubric-based grading review. Keep grading decisions traceable, consistent with rubric versions, and safe for human approval before publishing.

## Workflow

1. Load the assignment, rubric, submission, and relevant historical feedback.
2. Verify rubric version, course scope, student identity scope, and submission status.
3. Identify evidence in the submission before drafting feedback.
4. Draft feedback in Markdown with strengths, issues, rubric mapping, and next-step suggestions.
5. Save feedback as a draft before any publishing action.
6. Require human approval before invoking high-risk publishing tools.
7. Record tool side effects and approval metadata in the session summary.

## Safety Rules

- Treat `publish_grade` and student notification as high-risk actions.
- Require an idempotency key based on `submission_id+rubric_version` for publishing.
- Do not expose private student data outside the approved channel or course scope.
- Do not infer missing scores without rubric evidence.

## References

- Load `references/rubric-guidelines.md` when rubric interpretation is ambiguous.
