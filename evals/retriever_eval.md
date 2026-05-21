# Retriever Evaluation

## Dataset

Create a gold set with query, expected source IDs, modality, tenant scope, and answerable evidence.

## Metrics

- hit-rate
- MRR
- recall@k
- precision@k
- nDCG
- p50/p95 latency

## Query Classes

- Text-only questions.
- Visual-only questions involving charts, formulas, screenshots, or page layout.
- Mixed questions requiring text and page evidence.
- Permission-filtered questions requiring tenant/course scope.

## Baselines

- Text-only dense retrieval.
- Text hybrid retrieval.
- Text + visual retrieval with rank fusion.
- Text + visual retrieval with reranker.
