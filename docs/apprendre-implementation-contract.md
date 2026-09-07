# Apprendre implementation contract

This document fixes the interfaces for the parallel implementation. It refines the draft plan into a deliverable scope; it does not claim official CEFR/TCF certification.

## Ownership and integration

- Platform owner: Python, models/migrations, views, templates, JavaScript/CSS, routes and platform tests. Do not edit authored course content or the legacy curriculum.
- A1/A2/B1/B2 owners: only their own `study/content/learning/courses/<level>/` files and `study/content/learning/coverage/<level>.json`.
- Bridge owner: only `study/content/learning/courses/c1-preparation/` and its supporting authoring notes. No changes to exam scoring or platform code.
- Coordinator: benchmark snapshots, preservation manifest, integration, cross-owner decisions and final publication.
- No child pushes main, opens a PR or changes another owner's files. Commit your own completed work and send the commit SHA to the coordinator. Do not restore stale copies of shared files.
- Existing `curriculum.json` is a preserved reference library, not a shared writing target. All new original teaching goes into independently owned lesson files.

## Product surface

The main Apprendre hub presents the new structured course once content exists. Keep a clearly named reference-library view for all 83 published lessons, preserving their old routes, notes, annotation keys and manual completion. Search and links must make this library discoverable, not delete the user's Notion material.

Reuse the existing compact grouped table and small completion checkbox. Add course/reference scope and explicit CEFR filtering. Group course lessons by existing topic categories; do not build a complicated nested accordion tree. Previous/next follows level then lesson order and preserves the selected course scope. Do not reintroduce the removed standalone practice/vocabulary/takeaway panels on lesson pages.

Practice has its own page reached by a simple action on a course lesson. Original examples can use `**bold**` for the relevant French forms; render through the existing safe inline Markdown renderer, preserve line breaks and read-aloud text, and never expose raw HTML.

## Course lesson JSON: version 1

Each file is one complete JSON object, not an array. Example shape (illustrative placeholders, not a publishable lesson):

```json
{
  "version": 1,
  "id": "a1-sentence-foundations",
  "slug": "a1-sentence-foundations",
  "cefr_level": "A1",
  "topic": "grammar-foundations",
  "title": "Construire une phrase simple",
  "summary": "English description of the useful skill.",
  "order": 1,
  "duration_minutes": 10,
  "prerequisites": [],
  "objectives": ["An observable learner capability."],
  "keywords": ["French and English searchable concept names"],
  "sources": [
    {"label": "Reference actually consulted", "url": "https://example.org/"}
  ],
  "related_legacy_ids": ["grammar-articles-gender"],
  "sections": [
    {
      "id": "rule",
      "title": "A meaningful English heading",
      "paragraphs": ["English explanation, with French targets and definitions."],
      "points": ["A useful rule or limitation."],
      "examples": [
        {"french": "Une phrase **originale**.", "english": "An original sentence.", "note": "Why the highlighted form fits."}
      ],
      "mistakes": [
        {"avoid": "French error only", "prefer": "French correction only", "why": "English explanation."}
      ]
    }
  ],
  "practice": [
    {
      "id": "item-01",
      "kind": "text",
      "pool": "practice",
      "section_id": "rule",
      "prompt": "An English instruction specifying what to supply or transform.",
      "choices": [],
      "answers": ["A valid French answer"],
      "explanation": "Why the answer works; mention alternatives where appropriate."
    }
  ],
  "production_task": {
    "prompt": "A new communicative situation and clear instruction.",
    "model_answer": "An original French model, not an official exam response.",
    "translation": "Faithful English translation.",
    "rubric": ["A specific self-review criterion."]
  }
}
```

### Field rules

- `cefr_level`: exactly `A1`, `A2`, `B1`, `B2`, or `C1-preparation`.
- Directory and ID prefix agree: `a1-`, `a2-`, `b1-`, `b2-`, `c1-`.
- `topic`: one of the 10 existing module IDs in `curriculum.json`.
- `order`: unique positive integer within a level, chosen for a coherent progression.
- `prerequisites`: IDs of earlier course lessons. Prefer within-owner dependencies while authoring; coordinator may add cross-level links after integration. No circular or missing dependencies. No hard locks on reading.
- `related_legacy_ids`: real existing legacy lesson IDs; references are not a substitute for teaching the course lesson's own rule.
- `sources`: actual references, not invented citations. A benchmark index can be labelled a topic-coverage reference. Do not claim to have consulted an individual lesson or dictionary entry that was not read.
- Sections retain the legacy renderer's basic structure. Arrays `points`, `examples`, `mistakes` may be empty in an individual section. A lesson should provide at least eight genuinely useful examples overall and two genuine, context-appropriate corrections. Do not invent errors to fill a quota.
- All grammatical terminology is explained in English; French examples and their faithful translations remain visually paired. Vocabulary nouns introduced explicitly have article/gender in their explanatory headword.
- Paradigms must show every relevant person/form, not only `je` and `nous`. A multiline paradigm example is permitted, with aligned English lines.
- No copied or lightly paraphrased Kwiziq explanations, examples, exercises or proprietary sequence. Standard grammatical facts are taught independently.
- Most lessons should address one coherent decision/family in roughly 8–15 minutes. Complete coverage outranks an artificial lesson-count target.

## Practice and evidence

Each lesson has at least 16 manually authored items: at least 4 `practice`, 8 `check`, and 4 `review`. Add more when a large family or several benchmark distinctions require them. Every mapped benchmark topic must have relevant visible teaching and at least one identified practice item. Rewording only a name or a number does not make an independent item.

- `kind`: `text` or `choice`.
- A `choice` item has at least two distinct choices and answers that are members of that list. A text item has `choices: []`.
- `answers`: all explicitly accepted alternatives for this constrained task. Prompt tightly enough to avoid arbitrary rejection of equally valid sentences. Prefer asking for a particular form over pretending an unconstrained translation has one answer.
- Optional item booleans `case_sensitive` and `terminal_punctuation_sensitive` default to false. Set them to true when the item explicitly assesses that feature. Accents, morphology and internal punctuation such as inversion hyphens remain meaningful in all modes; do not guess normalization rules from prompt keywords.
- `pool`: `practice`, `check`, `review`.
- At least half of check/review items are `text` (unaided constructed answers), not only recognition.
- `section_id` must resolve within the lesson.
- Feedback is shown in learning mode. A check holds feedback until submission, uses server-side answer keys and records immutable item/content versions.
- Store self-declared reading completion separately from assessed course evidence; do not erase either. Existing completion is never converted to mastery.
- Initial bounded product criterion: a successful check requires at least 80% overall and 75% constructed-response accuracy; a separate successful review with fresh review-pool items is available at least seven days after a successful check. Clearly call this evidence of controlled grammar practice, not CEFR/TCF certification or permanently guaranteed mastery.
- Reading/production-task self-review is useful but cannot silently count as independently assessed free writing or speaking.
- Practice and review due remain available after failure; learning feedback/retries cannot silently become independent check evidence. Preserve results/history, show dates, and use deliberate server-side pool selection.
- Do not expose answer keys in initial HTML/JSON, accept arbitrary client scores, strip grammatical accents, or use an LLM/keyword heuristic to issue official-looking scores.
- Normalise harmless typographic apostrophes, surrounding/repeated whitespace and case when suitable; preserve accents and morphology. Reuse existing helpers where appropriate.
- Persist new learner data in export/reset/deletion paths and enforce per-user isolation.

The larger thresholds in the draft plan were unvalidated research proposals. This smaller, transparent pilot is implementable with a finite bank and does not warrant a broader claim. Any eventual certification-style claim requires a separately validated assessment.

## Coverage ledger for A1/A2/B1/B2

One file per level:

```json
{
  "version": 1,
  "level": "A1",
  "source_index_url": "https://french.kwiziq.com/revision/grammar/by-cefr-level/cefr-a1",
  "entries": [
    {
      "source_url": "exact URL from benchmark snapshot",
      "source_title": "exact short index title",
      "lesson_id": "a1-sentence-foundations",
      "section_ids": ["rule"],
      "practice_ids": ["item-01"],
      "disposition": "original-lesson",
      "evidence": "Specific explanation of where the underlying grammatical skill is taught and exercised."
    }
  ]
}
```

`disposition` is `original-lesson`, `consolidated`, or `recognition-track`. No `unreviewed`, generic “covered” evidence or empty mappings in the finished ledger. All source URLs must match that level's benchmark. Reusing one lesson for a verb family is welcome; every named form and exception still needs teaching and suitable exercise evidence.

Expected benchmark counts: A1 134; A2 165; B1 96; B2 84. Counts prove structural completeness only. Authors and reviewers must check the actual grammar and mappings.

## Bridge content

The C1-preparation directory teaches original transfer lessons for more precise, flexible language: register, sustained argument, comparing sources, tense/reference tracking, implicit meaning, self-repair and actual task fulfilment. Include reading passages and dialogues with faithful translations, and spoken/written production situations. It is a preparation bridge, not a fabricated complete C1 syllabus.

Use real existing URLs only for application links; ask coordinator/platform owner for route names rather than inventing routes. No external service is required. Do not claim synthetic speech demonstrates real listening readiness.

Verified target minimums for NCLC 9+: listening 523, reading 524, speaking 14/20, writing 14/20, separately. These thresholds fall in FEI's C1 test-score bands. No conversion from our practice percentages to TCF/NCLC scores. Sources and official task conditions are in `docs/apprendre-rebuild-plan.md`.

## Completion report from each owner

Give commit SHA, exact files, lesson/topic/example/item counts, checks run, grammar/source questions, remaining limitations, and any integration contracts needing attention. Do not say “perfect” or “fully equivalent” based on schema tests. Do not stop after writing only a few samples: the assigned scope must be fully authored and reviewed.

## Teaching-depth follow-up

The follow-up baseline is published commit `1e94f93c723fb11361137e8bc7d23adb18ac6231`: 120 A1–B2 lessons, nine preparation lessons and 479 topic mappings. The next review examines publicly accessible teaching bodies, rather than treating index-title coverage as evidence of matching explanation depth.

### Source use and honest scope

- Read each assigned benchmark's actual public teaching body. Use exact URLs from the benchmark/coverage files, follow ordinary public redirects and respect access restrictions. No authenticated question-bank extraction, access-control workarounds or bulk endpoint probing.
- Compare underlying grammatical facts and instructional needs: formation, meaning, scope, contrasts, exceptions, register, decision methods, correction rationale and contextual application.
- Do not reproduce or closely paraphrase the source's prose, tips, example bank, exercise bank or teaching sequence. Do not turn the audit into a substitute copy of the source course. New teaching and exercises must be independently written for our existing curriculum; use primary French references for disputed rules.
- Public lesson text is not the entire product. Subscriber questions, interactive assessment, community discussion and linked audio/video are outside this audit unless specifically and lawfully inspected. Inaccessible or partial material stays explicitly unassessed.
- Do not assume the reference is infallible. Qualify oversimplifications where authoritative grammar evidence warrants it. Do not invent gaps merely to increase a change count.

### Published-data preservation

- Level owners may edit only their level's course JSON, coverage ledger and new depth-audit JSON. The preparation bridge and preserved reference library are outside this follow-up authoring scope.
- Preserve lesson IDs, slugs, section IDs, item IDs, sources and cross-level preparation links. Prefer additive, coherently named teaching sections and useful examples over wholesale rewrites that disturb saved annotation text. Make targeted factual corrections where necessary and report them.
- Keep `version: 1`: it is the schema version. Content and item revisions already have computed hashes. Do not mutate historical learner attempts or pretend that an edited old item is unseen.
- Use stable new IDs for genuinely new exercises. Assess each newly introduced distinction with clear, constrained tasks and independent contexts; do not manufacture freshness by changing only a name, number or superficial wording.
- Expand check/review banks where real instructional gaps require it. No filler quotas or copied questions. The existing global question-uniqueness, constructed-answer and coverage requirements still apply.
- Keep English explanations and faithful French/English pairs, complete relevant paradigms and noun headwords with articles/genders. Include usable decision steps and meaningful contrasts rather than simply longer paragraphs.
- No new UI panels on reading pages. The existing teaching-section renderer and separate practice area remain the interface.

`study/content/learning/course_manifest.json` records the published baseline's 129 lesson identities, 348 section IDs, 2,169 item IDs, sources and preparation links. It was extracted from the baseline Git objects, not enriched working files. It is a preservation record, not another writing target. The reference library and nine preparation lessons remain byte-preserved; A1–B2 teaching may be enriched without removing published identities.

### Depth audit records

Each level owns `study/content/learning/depth/<level>.json`, with this separate report schema. It is not an extra field in course lessons or a claim of external certification.

```json
{
  "version": 1,
  "level": "A1",
  "baseline_commit": "1e94f93c723fb11361137e8bc7d23adb18ac6231",
  "scope": "public-lesson-text",
  "entries": [
    {
      "source_url": "exact benchmark URL",
      "source_title": "exact benchmark title",
      "checked_on": "2026-09-07",
      "access": "read",
      "finding": "enriched",
      "note": "A brief original factual gap or adequacy judgement, not a summary of the source lesson.",
      "evidence": [
        {"lesson_id": "a1-example", "section_ids": ["decision"], "practice_ids": ["depth-01"]}
      ],
      "references": [
        {"url": "actual additional grammar reference consulted", "purpose": "Why this reference was needed."}
      ]
    }
  ]
}
```

`access` is `read`, `partial` or `unavailable`; `finding` is `sufficient`, `enriched`, `reference-qualified` or `not-assessed`. A partial/unavailable entry must use `not-assessed`, explain its limitation and must not be counted as a completed depth comparison. `references` may be empty when no additional source was needed. Evidence must resolve to real teaching and exercise IDs in the same level. All 134/165/96/84 benchmark rows must be accounted for exactly once, with actual access and review status, not fabricated completion.

`validate_courses --coverage --depth` validates all four reports when explicitly requested. The normal course loader does not depend on research reports. Like coverage evidence, each evidence group links visible examples and questions exercising its mapped sections. Assessed comparisons need evidence; `not-assessed` entries may have none. A fully read page whose comparison remains incomplete may also be `not-assessed`. The command reports reading access and completed comparisons separately. Dates must be real `YYYY-MM-DD` values, never future dates. Structural validation cannot certify actual reading, teaching quality or external equivalence.

### Assessment workstream

Evaluate verified public product descriptions separately from undocumented algorithms or validation claims. Do not infer a proprietary formula from marketing language. Original improvements may make learning practice responsive to recent difficulty, improve section coverage in checks and report which sections remain untested. Preserve server-owned grading, finite-bank/freshness honesty, delayed-review rules, frozen results, account lifecycle and clean reading pages. Do not introduce an unvalidated mastery percentage, official-looking score, new pass threshold or claim of empirical equivalence.

The coordinator owns the depth-report validator, integration checks and final release record. Each author uses at most one independent editorial review of the new/changed teaching, questions and depth decisions, with focused follow-up for corrections. Report exact pages actually read, inaccessible pages, meaningful improvements, new exercise counts, preserved identities and remaining limits. Publish only a coherent completed follow-up, not another title-only coverage claim.
