# Apprendre: original A1–B2 curriculum and an NCLC 9+ preparation bridge

**Planning baseline:** 7 September 2026 · current application commit `a5715b1`.

**User goal:** exceptionally clear grammar teaching, with breadth comparable to the public Kwiziq A1–B2 topic catalogue, supporting **NCLC 9+ across all four TCF Canada skills**.

**Implemented release:** 120 original A1–B2 lessons resolve all 479 benchmark topics, with nine additional C1-oriented preparation lessons. The preserved 83-lesson reference library remains available with its existing routes, source material, notes and reading progress. The [implementation contract](apprendre-implementation-contract.md) records the concrete schema and bounded practice pilot that supersede earlier design alternatives below.

| Level | Original lessons | Paired examples | Practice items | Benchmark topics |
| --- | ---: | ---: | ---: | ---: |
| A1 | 33 | 364 | 546 | 134 |
| A2 | 36 | 290 | 582 | 165 |
| B1 | 26 | 267 | 480 | 96 |
| B2 | 25 | 294 | 417 | 84 |
| C1-oriented preparation | 9 | 72 | 144 | Separate bridge |
| **Total** | **129** | **1,287** | **2,169** | **479** |

These lessons contain 348 teaching sections, 303 contextual corrections and 129 production tasks with models, translations and self-review rubrics. A complete multiline paradigm counts as one example object, not several separate examples. The banks contain 540 learning-practice items, 1,081 check items and 548 review items; 1,960 require constructed answers.

All four benchmark ledgers contain exact source-title/URL mappings to actual teaching sections and exercise IDs. Separate AI-assisted editorial passes covered each complete level and ledger; source checks and integration review resolved grammatical variants, ambiguous instructions and duplicate cross-level questions. This is not human-teacher accreditation, psychometric validation or proof of equivalence to another platform's proprietary mastery score.

## 1. What success means

Apprendre should help a learner understand a rule, choose it for the intended meaning, form it accurately, recognise it in context, and use it in a new situation without copying a model.

Two outcomes must remain distinct:

- **Grammar coverage and demonstrated control:** the original A1–B2 curriculum addresses the benchmark's grammatical skills, including relevant exceptions, contrasts, register and receptive-only material.
- **TCF Canada readiness:** separate evidence from listening, reading, speaking and writing under the relevant task conditions. Grammar knowledge alone cannot establish NCLC 9, official CEFR certification, or equivalence to another platform's proprietary mastery score.

The A1–B2 core is the foundation, not a promise that finishing it guarantees the user's four-skill target. A clearly labelled advanced preparation bridge must address the additional control, comprehension and performance the target requires.

### The selected target is higher than a generic B2 outcome

The official IRCC TCF Canada table gives these **separate minimums for NCLC 9+**:

| Skill | Minimum target | Exact NCLC 9 band |
| --- | ---: | ---: |
| Listening | 523 | 523–548 |
| Reading | 524 | 524–548 |
| Speaking | 14/20 | 14–15/20 |
| Writing | 14/20 | 14–15/20 |

FEI's official TCF grid places **500–599** in reception and **14–17/20** in production in its **C1** bands. The chosen thresholds therefore fall within C1 bands on this test. NCLC and CEFR are different scales: do not replace their per-skill conversion with a universal equation.

The intended progression is consequently **A1–B2 grammar breadth → B2 consolidation and C1-oriented performance → four-skill readiness evidence**. B2+ means stronger B2 performance; it must not be presented as another name for C1.

The Council of Europe's descriptors also do not define B2 as error-free. They describe relatively high grammatical control, while C1 involves consistently high accuracy. Neither descriptor is a numerical quiz threshold.

Sources: [IRCC equivalence table](https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/language-test.html), [FEI score grid](https://www.france-education-international.fr/document/grilleniveauxtcf), [CEFR Companion Volume, grammatical accuracy p. 132 and plus levels p. 38](https://rm.coe.int/common-european-framework-of-reference-for-languages-learning-teaching/16809ea0d4).

## 2. What has actually been inspected

The public indexes contain the following distinct linked grammar topics:

| Benchmark | Topic links |
| --- | ---: |
| [A1](https://french.kwiziq.com/revision/grammar/by-cefr-level/cefr-a1) | 134 |
| [A2](https://french.kwiziq.com/revision/grammar/by-cefr-level/cefr-a2) | 165 |
| [B1](https://french.kwiziq.com/revision/grammar/by-cefr-level/cefr-b1) | 96 |
| [B2](https://french.kwiziq.com/revision/grammar/by-cefr-level/cefr-b2) | 84 |
| **Total, with no duplicate URLs across these indexes** | **479** |

These are **topic-index counts**, not a claim to have read, copied or audited 479 complete lessons. Several entries teach individual verbs within a family. We should not produce 479 arbitrary pages merely to match a competitor's page count.

The preserved reference library contains **83 lessons, 186 teaching sections and 10 topic categories**. Its difficulty labels are `Fondamental`, `Intermédiaire` and `Avancé`, not A1/A2/B1/B2. At the planning baseline, eleven lessons were estimated at 25 minutes or longer; one lexical lesson was 52 minutes with 12 sections.

Important baseline findings:

| Current evidence | Rebuild implication |
| --- | --- |
| The numbers lesson explains number agreement and ordinals, but not a complete progression for telling time, decimals and fractions. | Add explicit, contextual teaching rather than treating a broad title as coverage. |
| `verbs-future` combines the near future, simple future, irregular stems and future time clauses. | Separate introductory forms from later tense selection and sequence. |
| The future perfect appears in time-clause explanations, but lacks a complete standalone formation-and-use progression. | Add a dedicated skill sequence with auxiliary choice, formation and contrasts. |
| `prepositions-time-duration` contains strong explanations of `depuis`, `pendant`, `pour`, `en`, `dans` and past reference points in one section. | Preserve the accuracy; split the instructional sequence into digestible decisions. |
| Many long sections contain numerous rules but few opportunities to distinguish them independently. | Coverage must be assessed at skill level, not by counting examples in a large lesson. |
| Completion stores only a start date and optional completion date. | Preserve self-assessment, but do not rename it objective mastery. |
| Source-derived vocabulary, spelling and writing material extends beyond the benchmark. | Preserve useful existing material; the benchmark is a floor for grammar breadth, not a reason to delete the user's notes. |

## 3. Use sources without reproducing a proprietary course

Use the public topic indexes as an external coverage checklist. Where clarification is necessary, consult a specific public lesson and primary grammar references, then independently formulate the skill, explanation, examples and assessment.

Do **not** bulk rewrite Kwiziq's lesson text, paraphrase it paragraph by paragraph, reuse its example or quiz bank, mirror its exact instructional sequence, or claim access to its mastery algorithm.

Each original lesson should have a source record identifying the grammatical references actually consulted and the review date. Primary references such as OQLF, the Académie and recognised dictionaries should resolve disputed claims. Accepted French variants must not become errors merely because an index title gives a simplified rule.

## 4. Build a skill map before writing at scale

The planning-stage session register, `apprendre-a1-b2-coverage-register.json`, contained **479 rows**, with ten initial teaching-level checks and 469 awaiting review. It is a historical baseline, not the release ledger. The completed `study/content/learning/coverage/{a1,a2,b1,b2}.json` ledgers now resolve all 479 topics into original teaching and exercise evidence against the committed public-index snapshots. Mapping a topic does not mark a learner assessed or proficient.

For every row, record the benchmark topic, our original skill ID, current lesson/section evidence, prerequisite skills, introduction level, later consolidation level, and disposition:

| Disposition | Required evidence |
| --- | --- |
| Reuse and refine | Existing visible teaching explains the rule, relevant limitations and examples; specify what still needs assessment. |
| Split and strengthen | Material exists, but is buried, mixed-level, insufficiently explicit or insufficiently contrasted. |
| Add | The skill needs original teaching and examples. |
| Recognition track | The learner needs to understand the construction when reading/listening; routine production is not a priority. |
| Consolidate | Multiple benchmark entries are covered by a shared original lesson, with each distinct form/exception still demonstrably taught. |

Do not infer coverage from a title, a keyword match, a vocabulary entry, or one incidental sentence. Each finished mapping needs **a rule location, an example/contrast location and an assessment link**.

No benchmark topic is silently dropped for being less useful to the exam. Lower-frequency material can be put in a recognition or reference track with a clear explanation.

The final lesson count follows the skill map. One coherent learner decision may cover several source topics; a currently oversized lesson may become several short lessons.

## 5. Navigation and progression

Keep the familiar compact table, collapsed topic groups, search, small completion check and existing visual identity.

Add an explicit level filter: **A1 · A2 · B1 · B2 · Advanced preparation · All**. Within a selected level, reuse the existing topic grouping rather than adding several levels of nested accordions.

Retain one canonical home for each lesson. Level, topic and practical application are separate metadata dimensions, not duplicated copies of the same lesson. “Next lesson” should follow the chosen learning path, not merely the physical order of a JSON file.

Use a short foundations orientation for learners who still need subjects, verbs, infinitives, gender, number and essential sound–spelling relationships. A public A1 index should not be assumed to contain every absolute-beginner prerequisite.

| Stage | Main learner capability | Progression emphasis |
| --- | --- | --- |
| A1 | Build and understand clear everyday sentences. | Subjects; `être`/`avoir`; present families; articles and agreement; possession and reference; basic negatives/questions; place, time, numbers; near future and everyday constructions. |
| A2 | Describe experiences and manage practical exchanges. | Passé composé and imparfait foundations; reflexives; object pronouns; `y`/`en`; commands; comparisons; fuller questions/negation; durations and common verb distinctions. |
| B1 | Connect events, explain choices and handle less predictable situations. | Narrative tense choices; future and conditional; hypotheses; relative clauses; reference tracking; comparison nuance; gerunds; precise linking and verb constructions. |
| B2 | Express complex relationships with controlled grammar. | Subjunctive formation and selection; pluperfect, conditional past and future perfect; double pronouns; complex relatives; agreement cases; causatives; concession, purpose and nuanced stance. |
| C1-oriented preparation | Apply language flexibly and reliably to the four-skill target. | Dense meaning, inference, reformulation, discourse control, spontaneous interaction, precise writing and repair under time pressure. This is not automatically a complete C1 course or a guarantee of a C1 score. |

Level assignments are instructional decisions supported by the crosswalk and task demands, not official CEFR certification for individual grammar rules.

Suggested earlier-reading links connect relevant foundations across levels: present spelling, compound-past formation, narrative contrast, inversion, object pronouns and advanced time/stance interpretation. These are helpful reading references, not mandatory completion locks.

## 6. Non-negotiable lesson standard

Each focused lesson should normally take about 6–12 minutes to read actively, excluding practice. Longer reference tables remain available where useful; the timing is a design target, not a reason to cut essential explanation.

| Element | Standard |
| --- | --- |
| Useful objective | State what the learner will understand or be able to do. |
| Plain-English rule | Explain the decision before naming technical terminology; define new terms. |
| Formation | Show a compact pattern or complete relevant paradigm, with pronouns and agreement. |
| Meaning and scope | Explain when the construction fits and when a different construction is needed. |
| Examples | Use original natural French, faithful English translations, and a note explaining the highlighted form. |
| Contrasts | Compare closely related meanings with minimal changes, not unrelated sentences. |
| Exceptions | Show relevant exceptions with examples; distinguish introductory rules from later refinements. |
| Common corrections | Use genuine errors. If both sentences are grammatical, explain the meaning/register contrast instead of crossing one out. |
| Register and regional usage | Explain ordinary spoken versus careful written usage; label relevant Canadian/European differences without inventing rules or rejecting valid variants. |
| Application | Use a short realistic situation that requires the grammar, not a decorative exam label. |

Typical coverage should include several scaffolded examples, at least one meaningful contrast, and examples of each exception actually taught. The acceptance criterion is instructional completeness—not a rigid quota of filler sentences.

French examples should visually emphasise the relevant verb, ending, pronoun or connector. Do not highlight entire paragraphs. Emphasis must remain understandable without colour, preserve readable translations and work with read-aloud.

For nouns introduced as vocabulary, retain the article and gender. A new noun should not require the learner to leave the lesson merely to understand its central examples.

Avoid unexplained “Core concept” headings, false absolute rules, giant lists of unexplained words, obscure examples before basic ones, fabricated evidence, and formulaic instructions to force advanced grammar into every response.

The [original teaching prototype](apprendre-teaching-prototype.md) demonstrates the proposed clarity and depth.

## 7. Prepare for the four skills without turning every page into an exam guide

Keep Apprendre's general-learning presentation and clean reading pages. Use an application tag or a brief integrated scenario where it is useful; reuse the existing expression/comprehension areas for substantial task practice.

| Skill | Grammar transfer to practise | Evidence beyond grammar |
| --- | --- | --- |
| Listening | Hear negation, tense/aspect, pronoun references, quantities, time relationships and stance. | Unseen audio, normal delivery, different voices, inference and comprehension before seeing a transcript. Text-to-speech is a study aid, not proof of listening readiness. |
| Reading | Track people/ideas, temporal sequence, restrictions, concession, purpose, implicit position and complex sentences. | Unseen texts of varied forms and difficulty, with timed understanding rather than isolated grammar identification. |
| Speaking | Introduce and describe naturally, ask useful questions, follow up, narrate, explain and defend a position. | Relevant spontaneous content, intelligibility, interaction, repair, fluency and register—not merely a conjugation score. |
| Writing | Complete the requested communicative task, give precise information, narrate and organise or compare viewpoints. | Task fulfilment, audience, coherence, vocabulary, accuracy and word limits. No mandatory ornate introductions or fabricated statistics. |

Examples should range across housing, work, study, transport, services, relationships, leisure, health and community issues—not only administrative forms.

Examiner prompts can support formative feedback, but must not issue an official-looking score or a guaranteed NCLC result. AI estimates must remain explicitly estimates, with visible reasons and uncertainty.

### Official task conditions to use for exam-format practice

| Component | Current FEI format |
| --- | --- |
| Listening | 39 questions in 35 minutes; each recording plays once. |
| Reading | 39 questions in 60 minutes. |
| Speaking | Three tasks: 2-minute guided interview; 5 minutes 30 seconds for information-seeking interaction including 2 minutes of preparation; 4 minutes 30 seconds of spontaneous viewpoint development. |
| Writing | Three tasks in 60 minutes: addressed message of 60–120 words; experience/account with relevant commentary of 120–150 words; comparison of two supplied viewpoints and personal position in 120–180 words. |

Learning mode may allow replay, hints and feedback. Exam-format checks must use unseen material and the relevant constraints. Do not create an invented automatic word-count penalty or convert percentage-correct directly into TCF's difficulty-adjusted reception score.

TCF Canada has no separate grammar-structures paper. Do not import that component from TCF tout public by mistake. FEI evaluates linguistic, pragmatic and sociolinguistic performance, so grammar is one part of production quality.

Sources: [FEI TCF Canada format](https://www.france-education-international.fr/test/tcf-canada?langue=fr), [FEI evaluation criteria](https://www.france-education-international.fr/article/evaluation-epreuves-tcf), [FEI result interpretation](https://www.france-education-international.fr/article/comprendre-mes-resultats-au-tcf).

## 8. Completion and mastery must remain different

**Implementation decision:** add a separate controlled-practice area, following the user's subsequent instruction to carry out the complete rebuild. Do not redesign the clean lesson page or restore removed standalone practice, takeaway or vocabulary panels. Use the bounded pilot in the implementation contract, not an unvalidated proprietary-style mastery score.

Keep the existing manual completion check and its history. Store assessed evidence separately. Reading a lesson or importing an old completion must never silently award mastery.

The initial practice sequence is:

1. Untimed learning practice with specific explanations and explicitly recorded hints.
2. A separate check with feedback withheld until submission.
3. A distinct review pool, available at least seven days after the first successful check.
4. A contextual production task with a model, translation and self-review rubric, kept separate from independently assessed evidence.

Item types should include meaning discrimination, short production, transformations, error repair and contextual application. Multiple-choice recognition alone is insufficient. Changing only the names in a repeated sentence does not make it a strong independent holdout.

Each lesson has at least four learning items, eight check items and four distinct review items. At least half of each check and review pool requires constructed answers. Add more items wherever the mapped distinctions need them. These deliberately bounded banks provide limited grammar-practice evidence, not comprehensive or permanent mastery. Item reuse is useful for learning but must be labelled rehearsed, not independent evidence.

The implemented pilot gates are **80% overall and 75% on constructed responses**, followed by the separate delayed review. These are transparent product rules, not validated CEFR, NCLC or Kwiziq scoring rules. The earlier candidate involving twenty opportunities, three sessions and larger holdouts is not part of this release. Larger banks and teacher-calibrated transfer would be needed before stronger claims could be justified.

A failed first check must not permanently strand the learner. A successful, clearly labelled rehearsed check can unlock the delayed review, while the first failure and check freshness remain recorded. Review retries also remain available, but rehearsed success cannot substitute for successful fresh review. Track stable item identities and prompt exposure across content versions; a cosmetic rewrite does not create an unseen question.

Provide corrective feedback during learning, distinguish unaided first attempts from hints/retries, and never let a high recognition average conceal weak production or an untested strand. A single contextual response also cannot establish spontaneous speaking ability.

Show learning, check and review outcomes separately, with freshness, assistance and exhausted-bank limits visible. Do not imply permanent mastery or erase an earlier result when recommending further review.

Use deterministic grading only where accepted answers can be specified reliably. Normalize apostrophe styles and whitespace; ignore case and terminal sentence punctuation unless the item explicitly enables the corresponding sensitivity flag. Preserve accents, agreement and internal punctuation such as inversion hyphens. Accept legitimate spelling and grammatical alternatives. Open production needs a visible rubric and cautious self-review, not keyword matching or silent AI certainty.

Retrieval and delayed transfer are supported by [Roediger and Karpicke (2006)](https://doi.org/10.1111/j.1467-9280.2006.01693.x) and [Butler (2010)](https://pubmed.ncbi.nlm.nih.gov/20804289/). These studies support design principles; they do not validate French proficiency cutoffs. Use explicit criteria and reviewer calibration for open responses, consistent with the Council's [classroom assessment guidance](https://www.coe.int/en/web/common-european-framework-reference-languages/classroom-assessment).

## 9. Technical implementation

| Surface | Implemented design and safeguard |
| --- | --- |
| Content organisation | Add independently owned lesson JSON files and exact coverage ledgers. Preserve the existing `curriculum.json` reference library unchanged. Integrate serially; do not repeat simultaneous writes to one curriculum file. |
| Schema | Validate CEFR level, topic, stable lesson and item IDs, prerequisites, version, source records, teaching sections, practice pools and contextual production. Existing reference difficulty labels remain distinct from CEFR levels. |
| Loading | Preserve typed validation and caching. Emit only the information needed for the hub; do not embed the detailed teaching or answer banks of the expanded course in every page. |
| Lesson rendering | Reuse current sections, examples and corrections. Add safe structured emphasis/table support only where needed; do not inject raw HTML or break read-aloud and annotation text. |
| Search/navigation | Index French and English concept names and aliases, filter by level/topic, preserve progressive enhancement and remembered table/card preference. |
| Existing progress | Keep stable IDs/slugs where the lesson remains the same. Do not translate old `completed_at` into assessed competence. |
| Routes and references | Keep existing `/apprendre/<slug>/` reference routes and annotation keys. Add `/apprendre/cours/<slug>/` course routes and their separate practice pages; retain an explicit reference-library scope on the hub. Never silently reattach old notes. |
| Assessment data | Store immutable item/version attempts and derived skill evidence separately from manual completion, with per-user access control. |
| Account features | Include any new learner records in account export and reset/deletion paths, as existing Learn progress is today. |
| Other pages | Keep home summaries, notes, previous/next links and expression/comprehension integration consistent. |
| Release control | Keep integration private until the complete curriculum and acceptance gates are ready. The course catalogue becomes the default hub when its files are deployed; do not deploy partial authoring batches. |

Before migration, make a manifest of all 83 published lesson IDs/slugs, section annotation keys and source coverage. Test compatibility against that manifest. Content moved to a different route needs an explicit policy, not accidental orphaning.

## 10. Execution sequence and release gates

| Phase | Deliverable | Gate before advancing |
| --- | --- | --- |
| 1. Crosswalk | A reviewed disposition for all 479 benchmark rows, our original skill graph and preservation manifest. | Every topic mapped or explicitly classified; no keyword-only coverage claims; prerequisite graph coherent. |
| 2. Teaching prototypes | Representative A1, A2, B1 and B2 lessons, plus their independent practice items. | Clear rules, correct French, faithful translations, meaningful contrast and usable mobile presentation. |
| 3. Content infrastructure | Versioned manifest, lesson files, metadata, level filtering and compatibility handling. | Existing links, notes, self-assessed progress, search and compact controls still work. |
| 4. A1 and A2 authoring | Complete original foundational and lower-intermediate sequence. | Every assigned skill has visible teaching, examples and independently reviewed assessment coverage. |
| 5. B1 and B2 authoring | Complete original intermediate sequence, with production and recognition tracks. | No unresolved high-impact grammar errors, missing exceptions or untested claimed skills. |
| 6. Advanced preparation | Explicit bridge from the core to the selected NCLC target; links to genuine four-skill tasks. | Scope and score language honest; task conditions and requirements checked against current official sources. |
| 7. Assessment pilot | Separate practice, delayed review and evidence-based progress. | Accepted-answer behaviour, hints, retry isolation, holdout items and feedback reviewed; thresholds labelled as product decisions. |
| 8. Final publication | Reconciled original curriculum, coverage report, migration evidence and working user journeys. | Full topic ledger resolved, no source-content loss, no broken references, no misleading mastery claims. Publish only the coherent finished release. |

Authoring is manual, skill by skill. Scripts may validate schemas, count mappings, find duplicates and preserve identifiers; they must not mass-generate teaching or fabricate audit completion.

If work is delegated, each writer owns separate files. A different reviewer reads the actual teaching and answer bank. Integration has one owner and uses checked current revisions, not stale full-file snapshots.

No reliable total lesson count, completion time or score guarantee should be invented before the crosswalk and prototype pass.

## 11. Definition of done

- All 479 benchmark topics have reviewed mappings; consolidations and recognition-only decisions are explained.
- Every claimed taught skill has an explicit rule, appropriate examples/contrasts and the promised practice coverage.
- Existing Notion/PDF content is retained, improved or deliberately relocated with provenance.
- Levels and prerequisites form a usable progression; advanced edge cases do not overwhelm introductory lessons.
- No accepted variant is incorrectly marked wrong; English explanations and translations are independently checked.
- Lessons, navigation, table disclosures, search, read-aloud, notes and completion work on mobile and desktop.
- Self-assessed completion, grammar evidence and four-skill readiness are clearly distinguished.
- Score and exam-format claims are traceable to official current sources.
- The production release is persistent, reviewable and recoverable; unfinished material is not silently presented as mastered coverage.

## Planning artifacts

The original research artifacts remain in the session. Committed benchmark metadata, the legacy preservation manifest and completed coverage ledgers support reproducible release checks; none contains a copied proprietary lesson or quiz bank. Run `python manage.py validate_courses --coverage` and `python manage.py test study.tests.test_course_bundle` to check the complete bundle, mappings, question uniqueness, prerequisite ordering and preserved routes.

- `kwiziq-index-a1.json`, `kwiziq-index-a2.json`, `kwiziq-index-b1.json`, `kwiziq-index-b2.json`: public topic metadata snapshots.
- `apprendre-a1-b2-coverage-register.json`: historical planning register with 479 rows and ten initial teaching-level checks.
- `apprendre-coverage-spot-checks.json`: evidence and planned disposition for the ten inspected topics.
- `apprendre-published-preservation-manifest.json`: all 83 published lesson identities and 186 annotation keys.
- `apprendre-teaching-prototype.md`: original example of the proposed teaching standard.
- `study/content/learning/benchmarks/`: committed factual index snapshots.
- `study/content/learning/coverage/`: complete per-level release mappings, supplied by the respective curriculum owners.
- `study/content/learning/legacy_manifest.json`: committed preservation baseline for published identities, sources and annotation keys.

This plan is intentionally more demanding than replacing paragraphs. The meaningful outcome is a coherent, original learning system with traceable coverage and observable application.
