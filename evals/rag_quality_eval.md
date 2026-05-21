# RAG Quality Evaluation

## Answer Metrics

- Faithfulness to retrieved evidence.
- Answer relevance.
- Citation coverage.
- Hallucination or unsupported-claim rate.
- Contradiction rate against source documents.

## Review Checklist

- Every factual claim should map to evidence.
- Sensitive data should not be disclosed across scope boundaries.
- Missing evidence should produce uncertainty, not fabrication.
- High-risk tool recommendations should mention approval requirements.

## Regression Gates

- No answer should cite evidence outside the permitted tenant or course scope.
- No generated feedback should publish grades without approval metadata.
- No memory write should occur without source and scope.
