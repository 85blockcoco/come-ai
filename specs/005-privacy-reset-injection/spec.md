# Feature Specification: Privacy Reset and Injection Isolation

## Requirements

- Career reset deletes private databases, generated CVs, letters, dossiers and temporary exports, and is idempotent.
- Reset never deletes files outside the Career-owned directories.
- Offer text is untrusted data. Prompt-like passages cannot reach generated letters or CVs.
- Only facts and requirements accepted by the offer-intelligence snapshot may feed application documents.

## Acceptance

Synthetic reset and multilingual injection tests pass with no network or personal data.
