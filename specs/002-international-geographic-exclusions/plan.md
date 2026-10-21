# Plan — International geographic exclusions

Extend the existing search-brief contract rather than creating a second
filter. Apply the policy inside `qualify_offer`, before ranking, so a relevance
score can never override a geographic exclusion. Keep the interface as an
explicit projection of the saved brief. Validate locally with synthetic data;
no connector network call is required.
