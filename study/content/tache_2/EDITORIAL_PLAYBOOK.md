# Expression orale — Tâche 2 editorial playbook

This is the canonical internal standard for generating, revising, and reviewing
the application's TCF Canada Expression orale, Tâche 2 dialogue models.

It applies to:

- `study/content/tache_2/dialogues/*.json`
- `study/content/tache_2/subjects/hints.json`
- the English prompt notes attached to semantic dialogue models
- any review or generation work that changes those files

The source prompt always has priority. A useful question that does not fit the
prompt, role, relationship, or facts is still a wrong question.

## 1. Understand the prompt before writing

Record the following before drafting:

1. **Candidate role:** Who is asking for information?
2. **Interlocutor role:** Who holds the information?
3. **Objective:** What real decision or action must the candidate prepare?
4. **Known facts:** Which details are already stated and must not be asked again?
5. **Implied facts:** What would the relationship make naturally known?
6. **Register:** Does the relationship require `tu` or `vous`?
7. **Scope:** Which topics belong to this person, and which require another source?
8. **Setting:** Are the place, transaction, date, property, event, or service fixed?
9. **Ambiguities:** Which uncertainty must be clarified before narrower questions?

Relationship words carry information. For example:

- `ami(e)` usually implies `tu` and some shared knowledge.
- `voisin(e)` implies that the candidate already has accommodation nearby.
- A friend helping with a move normally knows the current home and should not
  ask for its address as though speaking to a stranger.
- An employee, agent, receptionist, landlord, colleague, neighbour, or friend
  has a different information boundary. Do not make one role answer for another.

Each model note must be in English and briefly explain the role, objective,
known or implied facts, useful assumptions, information boundaries, and
`tu`/`vous` choice.

## 2. Build a real conversation, not a questionnaire

Every shared application model contains exactly **eight questions**. This is a
product convention for adaptable practice routes, not an official TCF quota.

Organize the questions into **two to four contiguous topic blocks**. Put them in
the order a person would normally need them:

1. clarify the essential situation or decision;
2. establish practical criteria, options, or constraints;
3. examine costs, conditions, access, or risks;
4. settle timing, next steps, or responsibilities.

The exact order depends on the scenario. A property viewing, moving day,
course registration, neighbourhood enquiry, job discussion, and administrative
procedure do not share the same natural sequence.

Questions must:

- remain directly relevant to the prompt;
- help the candidate make a real decision or complete a real action;
- avoid asking for information already given;
- avoid repeating an earlier information goal in different words;
- contain one main information goal, with only closely related supports;
- sound speakable in an ordinary conversation;
- use concrete examples or alternatives when they improve vocabulary or help
  the interlocutor give a precise answer;
- avoid generic filler when a concrete logistical or decision-making question
  would be more useful.

Do not remove useful examples merely to make a question shorter. Examples such
as documents, equipment, services, costs, schedules, transport options, safety
checks, or comparison criteria are instructional support when they remain
natural and relevant.

## 3. Target strong NCLC 7/8 language

Use precise but natural French. The learner should be able to reuse the
structures without sounding memorized or artificially formal.

Across a dialogue, vary question forms naturally:

- `quel`, `où`, `quand`, `combien`, `comment`, `pourquoi`;
- `est-ce que`;
- suitable inversion with `vous`;
- conversational forms with `tu`;
- polite conditional requests;
- comparisons and alternatives;
- genuine conditional follow-ups.

Do not vary grammar for its own sake. Clarity, role accuracy, responsiveness,
and coherence matter more than forced inversion or unnecessarily complex syntax.

Prefer specific formulations:

- `Le quartier est-il plutôt calme, familial ou animé, surtout le soir et le week-end ?`
- `Quels commerces sont accessibles à pied — épicerie, pharmacie ou boulangerie ?`
- `À part les commerces, quels services trouve-t-on à proximité — clinique, bibliothèque ou centre communautaire ?`
- `Quels équipements sont indispensables : une buanderie, un balcon, du rangement ou un stationnement ?`
- `Quels sont les objets les plus encombrants ou les plus lourds à déplacer ?`

Avoid vague formulations such as `Comment est le quartier ?` when the real
information goal can be named.

## 4. Keep information goals distinct

Do not overload one question with several independent decisions merely to fit
more content. In particular, distinguish:

- **ambiance:** calm, family-oriented, lively, evenings, weekends;
- **shops and services:** grocery store, pharmacy, clinic, library;
- **transport:** routes, frequency, travel time, car-free access;
- **housing facilities:** laundry, balcony, storage, parking;
- **price:** base price or rent;
- **additional costs:** utilities, taxes, fees, deposits, parking, cleaning;
- **condition:** repairs, defects, age, warranties;
- **procedure:** documents, application, authorization, response time.

A single question may combine closely related details, such as bedrooms, beds,
and sleeping capacity, or rent and included utilities. It should not combine
neighbourhood atmosphere, transport, services, price, and property condition.

## 5. Respect practical and factual reality

Use details that fit the country, city, relationship, and transaction. Keep
names, places, prices, dates, objects, and later references consistent.

Examples:

- A normal sofa is not usually fully dismantled, but its legs may be removable.
- Wardrobes, beds, tables, desks, shelves, and modular furniture may be
  dismantled when the answer establishes that.
- A rental discussion uses rent, lease, utilities, application documents, and
  move-in dates; do not drift into purchase terminology.
- A purchase discussion may need sale price, annual property taxes,
  condominium fees, planned work, special assessments, and a viewing.
- A friend can offer local experience but should not make authoritative legal
  guarantees.
- Questions about legal rules should direct the learner to the competent
  official source when the answer depends on jurisdiction.

Never invent a precise private address, rule, fee, or legal guarantee merely to
make an answer sound concrete. Fictional scenario details may be specific, but
they must remain plausible and internally consistent.

## 6. Write hidden answers as realistic examiner replies

Answers are internal simulation support and are not displayed as learner model
answers in the application.

Each hidden answer must:

- directly answer every clause of the question;
- sound like a quick, realistic reply from the assigned interlocutor;
- remain declarative and contain no question;
- stay within 35 words;
- avoid volunteering unrelated information;
- avoid answering a later question prematurely;
- provide enough information for any marked relance;
- remain consistent with every earlier and later answer.

Check named-item continuity. If a conversation introduces a sofa, table,
television, and lamps, later questions about condition or price must not
silently omit an item unless the narrower scope is intentional.

## 7. Use relances only when the reply genuinely drives them

Every model must contain at least one realistic conditional relance.

A relance must:

- depend on a concrete earlier answer;
- stay in the same topic block;
- point backward with the 1-based `follow_up_to` index;
- adapt to the actual item, place, date, option, or problem named;
- be skipped when the earlier answer already supplied the information;
- use a concise English `condition` of no more than 14 words.

Do not label an ordinary next question as a relance merely to satisfy
validation. Do not write a follow-up that ignores or mechanically repeats the
answer it follows.

## 8. Open and close naturally

The opening should establish the purpose without reciting the whole prompt.
It must fit the relationship and register.

The closing must:

- contain `merci`;
- reflect the information or decision reached;
- avoid introducing a new question or unexplained plan;
- remain short and natural.

## 9. Keep Pistes aligned and useful

Every reviewed model has exactly eight bilingual Pistes, one for each question
in final order.

Each Piste must:

- summarize the question's information goal rather than reproduce the answer;
- preserve useful examples, alternatives, or vocabulary when they aid learning;
- introduce no fact absent from the question;
- remain under 100 characters in each language;
- use a concise, natural noun phrase;
- match the question after every rewrite;
- be meaningfully equivalent in English and French;
- avoid private contact details.

The interface displays:

1. **English first**, in the stronger primary style;
2. **French second**, in the smaller muted style.

Pistes must remain grouped under the same topic headings and in the same order
as the dialogue questions.

## 10. Preserve approved work during revisions

Before editing:

1. inspect the current working diff;
2. identify wording explicitly approved by the user;
3. preserve all unrelated uncommitted changes;
4. edit only genuine remaining weaknesses;
5. update the hidden answer and both Pistes whenever a question changes.

Reuse a strong construction from another model when it fits the new role and
context. Do not copy it mechanically when the relationship, place, decision,
or information boundary differs.

### Targeted geography changes

Leave the **Arrivée & installation** theme unchanged. In other themes, retain
Canadian settings required by any source prompt in a shared semantic group.
For optional examples, prefer Seattle and nearby US destinations; substitute
US examples for locations outside Canada. Nationality is not a destination:
a Canadian friend may have travelled in the US. A francophone-country role
still requires a genuinely francophone country, such as Canada.

Change only place names and directly dependent details: local landmarks,
transport, climate, currency or tax terminology. Keep question structures,
order, topic headings, and unrelated learned vocabulary intact. Do not add a
named city to an otherwise generic question just to enforce this convention.
Treat private accommodation addresses, prices and event arrangements as
fictional scenario details, not verified listings.

Before changing visible model text, retain the previous opening, questions,
closing and layout in `dialogue_history/locations.json`, with exact geographic
substitutions. Never replace old revision entries when adding a later one.
The annotation endpoint recovers only known published revisions and verifies
saved quotes and contexts before projecting offsets. A selection on a replaced
place name follows the replacement; an unchanged field retains its selection.
Unrecognized or inconsistent anchors stay stored, not guessed or deleted.
Never rewrite learners' personal questions, private prompt notes or annotation
bodies as part of a geography edit.

## 11. Generation workflow

Use this sequence for every new or substantially rewritten model:

1. Read every source prompt represented by the semantic group.
2. Write the English role-and-scope note.
3. List known facts, unknown facts, and prohibited assumptions.
4. Choose two to four topic blocks.
5. Draft eight priority-ordered information goals.
6. Turn them into varied, speakable French questions.
7. Write short hidden answers and check continuity.
8. Mark only genuine relances.
9. Write the opening, conclusion, and eight bilingual Pistes.
10. Perform the review checklist below.
11. Run the focused validators.

## 12. Review checklist

### Prompt fidelity

- Does every question serve the exact prompt?
- Are candidate and interlocutor roles correct?
- Is the information holder realistic?
- Are known and implied facts respected?
- Is `tu` or `vous` correct throughout?

### Conversation quality

- Are there exactly eight useful questions?
- Are they ordered as a real conversation?
- Are topic blocks contiguous and coherent?
- Is every information goal distinct?
- Are examples relevant rather than decorative?
- Are question forms varied without sounding forced?
- Is at least one relance genuinely answer-dependent?

### Answer quality

- Does every answer cover every clause?
- Does it avoid answering later questions?
- Are all objects, places, prices, and dates consistent?
- Is the answer short, natural, and declarative?

### Learning quality

- Does the model teach reusable vocabulary and structures?
- Are useful practical details preserved?
- Are all eight Pistes aligned and bilingual?
- Does the note explain the prompt in English?
- Does the conclusion thank the interlocutor?

### Final regression review

- Compare the final model to the source prompt again.
- Compare the final questions to the previous working diff.
- Read the dialogue aloud for naturalness.
- Check that removing any question would leave a meaningful information gap.
- Check that no two questions could be answered with substantially the same reply.

## 13. Machine-enforced constraints

Current dialogue constraints include:

- exactly eight questions;
- two to four contiguous topic blocks;
- at least one valid conditional relance;
- 1-based, backward `follow_up_to` within the same topic;
- one terminal question mark per question;
- no more than 45 words per question;
- no more than 35 words per hidden answer;
- hidden answers cannot be questions;
- no more than 14 words per follow-up condition;
- every closing contains `merci`.

Current Piste constraints include:

- exactly eight Pistes for reviewed themes;
- one French and one English value per Piste;
- fewer than 100 characters per language;
- final order aligned with the questions.

Run:

```bash
.venv/bin/python manage.py test \
  study.tests.test_tache_two_dialogues \
  study.tests.test_tache_two_locations \
  study.tests.test_subject_hints \
  study.tests.test_question_bank \
  --noinput

git diff --check
```

Structural validation is necessary but not sufficient. Passing tests does not
prove that a dialogue is relevant, realistic, non-redundant, or well ordered;
the editorial checklist remains mandatory.
