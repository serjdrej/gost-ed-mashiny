# Development history

## Extraction (2026-09-10)

Started as `personal/gost-ed-mashiny` inside `lazy-skill-library`, with no
norms-registry, no lookup script, and no citation-verification mechanism —
only the structural content (intake questionnaire, РЭ/ПС structure guides,
ТР ТС 010/2011 audit checklist, style guide). Extracted into this standalone
repository the same day, mirroring `patent-ru`'s shape (MIT `LICENSE`,
`README.md`, root-level `SKILL.md`, `.claude-plugin/plugin.json`).

## Norms registry and lookup script (2026-09-10)

Built `references/norms-registry.md` and `scripts/gost_lookup.py` against a
real, confirmed-working source: Rosstandart's open-data portal
(`rst.gov.ru/opendata`), which — unlike `legal-ru`'s `publication.pravo.gov.ru`
— was reachable directly from an agent sandbox at the time, no geo-block, no
API key. Two catalogues matter here: «Каталог национальных стандартов» for
`ГОСТ Р` designations, «Каталог межгосударственных стандартов» for plain
`ГОСТ`. `scripts/gost_lookup.py status "<обозначение>"` downloads the
relevant CSV and reports the `Статус` column; `trts-route` points at ЕЭК's
navigation page for ТР ТС regulations, since no comparable open-data source
exists for those — an investigated candidate,
`docs.eaeunion.org/api/documents.php`, turned out to support only pagination
and date-range filters, no text/number search, and was rejected rather than
built against.

Live verification the same day found a real error: this project's own prior
references called the "паспорт" standard `ГОСТ 2.601-2019` (no `Р`)
throughout. The actual catalogue entry is `ГОСТ Р 2.601-2019` — zero matches
in the interstate catalogue under either the correct or the ГОСТ Р 2.610-2019
neighbour was found correctly on the first attempt. Corrected everywhere the
wrong designation appeared.

## First hygiene pass (2026-09-11, peer review from the marketplace)

A sibling session (`ru-legal-skills`'s own maintaining session, coordinating
across `legal-ru`, `patent-ru`, this repository, and later `arbitrazh-ru`)
ran a review pass and found: an undeclared external dependency
(`anthropic-skills:docx`, used in the DOCX-export step but named nowhere as
external); no `.gitignore` (the other two siblings had one); the description
named "станок" as a trigger with nothing in `references/` backing it; and a
one-row "Маршрутизация" table implying a multi-branch router where the
skill is actually a linear six-step process. All four fixed the same day.

A second pass from the same source found the standing disclaimer was present
but positioned as the last of several bullets rather than prominent — moved
above the fold in both `README.md` and `SKILL.md`.

## The silent-snapshot defect (opened 2026-09-19, closed 2026-09-19–20)

`scripts/gost_lookup.py` pinned both catalogue CSV filenames to
`data-20240808-structure-20220330.csv` with no indication anywhere in the
output that this was a dated snapshot rather than a live answer. The
marketplace session that found this also established, before leaving the
note, that `20240808` was genuinely the newest snapshot Rosstandart had
published (checked against the published list: `20220218, 20220330,
20230912, 20240508, 20240808`) — the defect was the silence, not staleness.
Left as `docs/pending-work.md` for the next session to pick up, per this
family's convention that a finding living only in another session's context
does not survive a compact.

Fixed the same way the note proposed, both halves together rather than
choosing one: `discover_data_url()` fetches each catalogue's open-data page
live and picks the *newest* listed snapshot by embedded date (not merely
the first one found — the page can list an archive of older files
alongside the current one), falling back to the pinned filename — itself
still downloaded and validated, never assumed fresh — only if discovery
fails. Every `status` result states the snapshot date, its source
(discovered live vs. pinned fallback), and the exact URL used.

## Full review and second round of fixes (2026-09-20, owner-authorized)

An Opus 5 in-session-subagent review (network access, an explicit
write-nothing constraint rather than a kernel sandbox — a prior dispatch of
the same brief to a different model had been killed by an account usage
limit before running a single command) produced ten numbered findings plus
several lower-priority observations. Each finding was independently
re-verified with a live command before being acted on, not taken on the
report's word — the review's own request, and this family's standing
practice.

Confirmed and fixed:

1. The gap-protocol's own worked example queried `ГОСТ 12.1.003` (no year);
   every row in both catalogues carries a year, so this returned a false
   "not found" for a standard that is `Действует` under
   `ГОСТ 12.1.003-2014`. Fixed the example, and — beyond what the review
   required — added a prefix-hint search: a miss now lists any designation
   sharing the query as a prefix, so a missing year surfaces as a lead
   rather than a dead end.
2. `SKILL.md` and `norms-registry.md` promised a status vocabulary
   (действует/отменён/заменён) the source does not carry. Measured directly
   against both live snapshots (14 955 and 24 043 rows): only «Действует»,
   «Принят», and, interstate-only, «Действует только в РФ» exist. A
   withdrawn or superseded standard is simply absent from the snapshot, not
   marked — corrected both files and the script's own not-found message.
3. Two worked examples in `SKILL.md` used section numbers
   (`2.3.5`, `5.1`) that contradicted `references/re-structure.md`'s actual
   numbering (2.3.5 = failure-mode list, not sound level; Часть 5 = storage,
   not critical failures) — an agent copying the examples verbatim would
   mislabel its output and fail the skill's own audit checklist. Renumbered
   to match (sound level → 1.1.2, critical failures → 4.1).
4. No test file existed anywhere in the repository; ten behaviours added by
   the previous day's fix were unprotected, and `pending-work.md` falsely
   claimed one was already covered by a test. Added
   `scripts/test_gost_lookup.py` (25 tests, stdlib `unittest`, no new
   dependency: pure-logic unit tests plus monkeypatched-`urlopen` tests for
   the failure branches a live run cannot reach on demand). The RED half was
   verified, not asserted: the same test file run against the pre-fix
   commit in a throwaway `git worktree` produced 5 passes and 20 failures —
   15 of those correctly identified as `AttributeError` on functions that
   did not exist yet (not miscounted as caught regressions), 5 as genuine
   assertion failures including the Latin-P routing bug (finding 10). All
   25 pass against the fixed code.
5. `discover_data_url()` picked the first `data-*.csv` match on a catalogue
   page rather than the newest; switched to comparing every match's
   embedded date.
6. The found branch lacked the staleness reminder the not-found branch
   already carried; added an equivalent line.
7. `references/trts-010-checklist.md` carried no paraphrase/status marker
   at the point `SKILL.md` step 5 actually routes an agent to it — the
   marker previously lived only in `norms-registry.md`, which that step
   never opens. Moved rather than duplicated.
8. `docs/pending-work.md` contradicted itself (marked "не начато" against
   its own later paragraphs describing the fix as done) and cited line
   numbers that had already drifted twice. Marked resolved with commit
   hashes and replaced line-number references with symbol names, since a
   line number in a file under active editing is a citation that expires.
9. `README.md` stated three things false at that point: the marketplace
   listed only two sibling plugins where it actually listed four; claimed
   this repository was "not imported anywhere" when it was (read-only,
   into `lazy-skill-library`, per that project's leading-dot import rule);
   and referenced a now-resolved defect as current. Corrected all three.
10. `choose_catalog()` matched only the Cyrillic `Р`, so a Latin `P`
    look-alike (visually identical, easy to mistype) silently misrouted to
    the wrong catalogue. Extended to accept both, confirmed live that a
    Latin-P query now searches the correct catalogue (the exact-match
    lookup still requires the correct character — the fix is routing, not
    silently correcting the query).

Also fixed in passing: a download failure previously dropped the snapshot
provenance from its error message; it now carries the same "discovered live
vs. pinned fallback" context as every other outcome.

Left for the owner's judgment, not acted on: whether this repository needs
a `NOTICE.md` given its structural resemblance to the family's shared
router/references shape (the review declined to answer this as a
measurement, correctly calling it a derivation judgment); and the separate,
explicitly-optional "Как править этот файл" recommendation recorded in
`docs/pending-work.md`.

## Testing status

- **Citation data**: live-verified against Rosstandart's open catalogues
  (2026-09-10, re-confirmed 2026-09-20) and against ЕЭК's navigation page
  for ТР ТС.
- **Behavioural/regression**: `scripts/test_gost_lookup.py`, 25 tests,
  covering both catalogue-selection logic and every failure branch added by
  the 2026-09-19/20 fixes; RED-before/GREEN-after verified against the
  actual pre-fix commit, not assumed.
- **Discipline under pressure** (RED→GREEN→REFACTOR against the "gap
  protocol" specifically): run 2026-09-14, recorded in `README.md`'s
  "Тестирование" section — not repeated here to avoid two sources of truth
  for the same result.

See [`ru-legal-skills/docs/review-checklist.md`](https://github.com/serjdrej/ru-legal-skills/blob/master/docs/review-checklist.md)
for the family-wide convention this repository is held to, and
[`ru-legal-skills/docs/norms-verification-convention.md`](https://github.com/serjdrej/ru-legal-skills/blob/master/docs/norms-verification-convention.md)
for the citation-registry shape it follows.
