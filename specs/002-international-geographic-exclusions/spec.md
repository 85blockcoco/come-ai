# Feature specification — International geographic exclusions

## User value

The candidate must complete the internship outside France. Career Explorer
must therefore exclude France and Paris by default, expose those exclusions as
editable search criteria, and keep an unknown or mixed location in “to verify”
rather than treating it as a confirmed international match.

## Requirements

- The first Career search uses `France` and `Paris` as visible exclusions and
  requires a known country.
- The user can edit or clear each exclusion; saved empty lists stay empty.
- A country or city matching an exclusion is `non_conforming`.
- A missing country or a mixed location containing an excluded city is
  `to_verify`, never `conforming`.
- Every discovery connector and stored-offer matching path receives the same
  saved criteria.
- No location is inferred from a title, company or language.
- This feature makes no network request and transmits no profile data.

## Success criteria

- Deterministic tests cover France, Paris, a foreign country, a missing place,
  a mixed city list and a deliberately cleared exclusion list.
- The API round-trip preserves the visible criteria.
- Existing Career and full-project tests remain green.
