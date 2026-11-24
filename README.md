# Heureux

Heureux is a Django study application. It combines guided French lessons,
model responses, reusable vocabulary, comprehension practice, spaced
repetition, notes, highlights, and explicit completion tracking.

## Local development

Local development uses Python 3.12. Render runs Python 3.11, so application code and migrations must also work on 3.11.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py import_content --if-changed
python manage.py runserver
```

Run the regular test suite with `python manage.py test`. Browser tests are kept
out of Django's default discovery because they require Playwright:

```bash
python -m playwright install chromium
python manage.py test study.tests.browser_tests study.tests.eo3_audio_browser_tests
```

For request/query regressions, use a **disposable PostgreSQL instance only**,
with a test role allowed to create databases. CI uses PostgreSQL 16. Replace the
local URL below with your owned test instance, never a production database.
Disabling server-side cursors matches the production Neon/PgBouncer configuration:

```bash
DATABASE_URL=postgresql://test_user@127.0.0.1:55439/heureux_test \
DB_DISABLE_SERVER_SIDE_CURSORS=True python manage.py test \
  study.tests.test_query_budgets \
  study.tests.test_retirement_query_performance \
  study.tests.test_expression_landing_performance \
  study.tests.test_eo3_detail_performance \
  study.tests.test_writing_request_performance
```

These cover the bundled corpus, private-response freshness, batched writing
activity dates, lean subject navigation, and retirement checks
against the original query semantics. A SQLite-only execution-step guard also
covers unrelated vocabulary growth, but cannot establish PostgreSQL performance.
Subject progress uses response-only queries for response cards and phrase-only
queries for vocabulary cards, retaining retirement checks and suspended activity.
Use `EXPLAIN (ANALYZE, BUFFERS)` on representative reads in an isolated seeded
PostgreSQL database to evaluate planner changes; production network round trips,
cold starts, concurrency and browser rendering require separate measurement.

EO2/EO3 subject directories expose aggregate `Server-Timing` response metrics:
`app` includes session/authentication, view work and template rendering; `db`
measures SQL execution, with the query count in its description. It excludes
connection setup/health checks and result fetching, which remain inside `app`.
Compression, upstream queueing, network transfer and browser work are outside
`app`. These headers contain no SQL text, parameters or learner identities;
they do not cache progress or change the page's private/no-store policy.

The Expression hub and oral/written landing pages are metadata-only navigation:
titles, descriptions, icons and links, without catalogue/progress/due counts or
statistics requests. Oral and written task links use the same flat, compact layout
regardless of the saved collection view. EO/EE task overviews aggregate only
the study progress they display without constructing full subject directories
or review links.
**Simulation** sits between **Notes** and search in the main navigation and opens
`/simulation/`. **Stats** is in the profile dropdown, above **Réglages**.
EO2 and EO3 use one speaking simulator. EE1 and EE2 use one private writing
simulator, with frozen prompts, draft saving and task-specific word limits
(60–120 and 120–150 respectively). EE3 still links to untimed subject practice.
The session templates live under `study/templates/study/simulation/`, and the
shared evaluation code lives in `study/simulation/`.
Writing sends the exact subject, the response, its word count and limits, and
the task’s grading instructions to the disclosed provider. Like the oral grader,
it verifies citations using numbered passages from the learner’s original words.
EE1 grading with Gemini 3.8 Flash uses the same `GEMINI_API_KEY` as the voice
simulator. Check [Google’s data-use terms](https://aistudio.google.com/docs/terms)
before grading learner responses: Google may use free-tier inputs to improve
its models. To add **Workers** (Cloudflare Workers AI’s Llama 3.3 70B) to EE1, set `CLOUDFLARE_WORKERS_API_KEY` and
`CLOUDFLARE_ACCOUNT_ID` on Render using the [Workers AI REST setup](https://developers.cloudflare.com/workers-ai/get-started/rest-api/).
Heureux calls Workers AI directly; see [Cloudflare’s data-use terms](https://developers.cloudflare.com/workers-ai/platform/data-usage/).
Set `EE1_EVALUATION_PROVIDER` to `gemini`, `groq`, or `cloudflare` to pick the
default when configured. When more than one model is available, the EE1
bilan’s sparkle button opens a model picker. Each report is saved separately;
switching back opens the saved report without grading again. EE2 and oral
grading stay on Groq. Only the selected provider receives the response. All
providers use the same evidence checks; optional feedback can be omitted
without hiding a supported score. Temporary service failures are retried once with the same
provider within the three-minute deadline. Groq can also use its one retry to
recover from a writing schema rejection in JSON mode.
With at least one provider configured, this command runs every available
provider on the same invented writing sample, without using learner responses:

```shell
RUN_WRITING_CALIBRATION=1 python manage.py test study.tests.writing_bilan_calibration
```

Writing criterion marks run from 1/5 (limited) to 5/5 (excellent); they are
practice indicators and are not added up to produce the overall estimate.
In **Simulation → Expression orale → Tâche 2 → Choisir un sujet**, the Sujets table
and its **Thème**, **Statut** and **Tri** filters let learners find a topic. Its title
opens the exact publication; the **Séances** count opens its history. **Terminé** is
a manual completion checkbox; **À refaire** is an independent bookmark. Both save
in place, so learners can mark several topics without reloading the page.
A saved EO2 session marks the topic done and adds one dated attempt. Changing
either marker or reopening a bilan never adds an attempt. Existing history
also retains older guided attempts, which have no transcript or audio.
Expiring a voice transcript keeps the practice count; explicitly deleting it removes
that occurrence. A progress reset clears attempts and checkmarks but keeps retry bookmarks.
The EO2 task overview is also metadata-only navigation, retaining its practice
prompt and links to subjects and vocabulary without summary statistics.
Content-bearing subject, vocabulary and question pages retain their learning
controls and data. Personal statistics remain private, uncached and recalculated
on each request where displayed. Oral annotation owners reuse request-local
identities; writing-model availability is projected without loading model JSON. Lot summaries
aggregate stable phrase units in SQL rather than transferring every card; suspended
units keep their original lot positions. No private progress is globally cached.

Exercise lean, JavaScript-free navigation against a disposable PostgreSQL instance:

```bash
DATABASE_URL=postgresql://test_user@127.0.0.1:55439/heureux_test \
DB_DISABLE_SERVER_SIDE_CURSORS=True python manage.py test \
  study.tests.expression_navigation_browser_tests
```

CI runs `database-locking` tests, including public oral annotation preservation,
against PostgreSQL. Use a disposable PostgreSQL `DATABASE_URL` with
`python manage.py test --tag=database-locking --parallel=1` to exercise the same
gate locally. SQLite alone cannot validate PostgreSQL row-lock restrictions on
nullable joins.

`BrowserTests` serializes live-server application work when Django shares an in-memory
SQLite connection between threads; overlapping transactions on that one
connection can otherwise cause spurious HTTP 500s or authentication failures.
Socket handlers stay threaded, including idle browser connections. File-backed
SQLite and PostgreSQL retain concurrent application work. Browser-side asynchronous
response-ordering checks still run with their controlled delays.

## Subject navigation

On EO Tâches 2/3 and EE Tâches 1/2/3 subject pages, the **Sujet N sur M**
counter opens a subject picker for the current theme or category. EO3 choices
are grouped by the display subthemes, in the same order as the subject directory.
Each picker keeps matching numbering, previous/next links, and the
publication-deduplication setting.

Subject bookmarks are private to each learner and independent of progress.
Use the bookmark beside the subject's progress controls or in its directory row;
saved bookmarks are filled red and persist across visits. In EO2, EO3 and all
three EE subject directories, bookmarking and marking complete save in place.
Counts and filtered rows update without closing an open theme or resetting your
sort. Copying the consigne on the subject page is unchanged.

### Tâche 2 · Exercice en interaction

Choose a topic under **Simulation → Expression orale → Tâche 2**. The session has
three stages: **Préparation → Échange → Bilan**. Notes on the scratch sheet
remain visible during the exchange. If the service is unavailable, the page
says so instead of opening a different exercise.

In the photo-workshop scenario, a French-speaking receptionist answers the
learner’s questions about two workshops. The interlocutor can be interrupted
and may misunderstand or invent facts. **Commencer la séance** opens the consent and PIN dialog.
Enter the PIN once for the attempt. Gemini reads the selected French prompt
with the microphone off and both clocks stopped. When playback finishes,
the **2:00** preparation countdown starts automatically. Skip the remaining
preparation or let it expire to open the exchange. Its **3:30** countdown
starts only when the microphone and the Gemini session are ready. At that
point a connection indicator appears and the interlocutor is asked to say
« Bonjour ! », then leave the first question to the learner. If reading
fails or is interrupted, preparation does not start.
Ending the exercise or leaving the tab closes
the call. The browser builds a speaker-labelled transcript from the live captions;
Gemini is told to expect French, so an accent is less likely to be captioned as another language.
The bilan groups the practice estimate, transcript, and Proposition into separate collapsible cards.
In the transcript, learners can reread their numbered turns with suggested changes shown inline:
the original wording struck through and its replacement highlighted, with the
reason just below the turn. They can reveal the
partner’s replies for context. The transcript is read-only; suggestions do not
replace the words used for scoring. An inline correction is shown only when its
word or phrase can be located unambiguously in that learner turn.
Strengths are illustrated with real questions or follow-ups from the exchange.
Unmarked text is not a blanket endorsement, and a spelling difference is not a pronunciation error. An interrupted
call can show the portion received; no learner speech means no assessment.
When time is up, Heureux starts a Groq evaluation automatically: the consent given before the
exchange covers sending its transcript to Groq for this bilan. A small spinner beside the
sparkle icon (**Évaluer mon niveau**) shows when the evaluation is in
progress; if it fails, select the icon to try again. No second PIN is needed for this attempt. Heureux sends only the
published consigne and both speakers’ transcribed words (not audio or notes)
to [`openai/gpt-oss-120b`](https://console.groq.com/docs/model/openai/gpt-oss-120b) on Groq,
which [may log them for up to 30 days](https://console.groq.com/docs/your-data) unless
Zero Data Retention is turned on in its data controls.
Heureux gives Groq three minutes to finish, counted across the whole reply, and logs the
token counts when a bilan is slow or unfinished. If Groq is briefly unavailable or the
connection drops, it resends the transcript once within that time. A failure message names
Groq’s error code, such as `HTTP 400 json_validate_failed`, which is also logged on the server;
a quota error also says when to try again whenever Groq does.
The strict response schema avoids length and range bounds, so
Heureux applies those limits after the reply instead. While it waits, the server sends a few blank keep-alive bytes so that a hosting
proxy does not end the request before the bilan arrives.
The debrief shows four practice marks **out of 5**: task completion, coherence
and flow of ideas, lexical precision, and grammatical accuracy. Each mark uses
Tâche 2 descriptors with indicative CEFR anchors (1 ≈ A2 up to 5 ≈ C2), and its
note says what the exchange showed and what would earn the next mark. Heureux adds them
for one **total out of 20** and maps it to **NCLC** and **CEFR**. This is a
practice rubric, not official TCF weighting. **Au prochain essai** gives one
action to practise, with an example specific to the task. In both studios, Heureux
labels short, unchanged passages of learner speech before grading. Groq selects
an ID for each mark and strength; Heureux displays the original passage linked to
its turn. Partner speech is context only and has no selectable IDs. This verifies
who said the words, not whether the grader interpreted them correctly. Feedback
should distinguish a poor word choice from a simple but precise one, and an
audible grammatical problem from a dictation spelling. A mark without a valid
passage is shown as **Non évalué**, not zero. EO2’s marks must also cover learner turns on either side of
a partner reply; EO3 can be assessed from one developed turn. Older reports
keep their original marks without retrofitting evidence. Up to twelve inline corrections identify the words to
change and why. The bilan also includes a **Proposition**: the learner’s
own turns, rewritten in order as a polished model they can copy and rehearse.
The reviewer receives both speakers’ captured turns in order, even when partner
replies are hidden in the UI. Each proposed line must point to the corresponding
learner turn. Groq is asked to keep questions as questions and personal answers
as answers, preserving who did what and what was known at that point in the
conversation. If the turn references do not match, the proposal is omitted;
matching references do not themselves verify a paraphrase’s meaning.
An unverifiable edit, strength or proposal is left out without discarding
a supported score. An incomplete rubric is not extrapolated to a total.
Pronunciation, pace and accent are not assessed from text.
To check the live grader after a rubric or model change, use the opt-in synthetic
calibration below with a configured `GROQ_API_KEY`. It makes four grading requests
(subject to provider quota), compares task-specific behavior rather than demanding
an exact mark, and does not read saved learner sessions. These are regression
signals, not validation against examiner ratings.

```bash
RUN_GROQ_CALIBRATION=1 python manage.py test study.tests.oral_bilan_calibration
```

Conversions follow the [TCF speaking scale](https://www.france-education-international.fr/document/grilleniveauxtcf)
and the [IRCC TCF Canada speaking table](https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/language-test.html#level).
This estimates one transcribed task, not pronunciation or the official
three-task speaking result. If Groq is unavailable, the transcript remains
available without a new score. Heureux never saves the audio. It saves the transcript when the
exchange ends and adds the bilan once it arrives, keeping the learner’s thirty most
recent sessions. The setup screen lists the five latest for that subject under
**Séances enregistrées**. Reopening one shows its stored bilan and corrections without
calling Groq again. If it has no bilan yet, the sparkle icon requests one with the PIN.
On a partial rubric the same icon, **Réévaluer le bilan**, requests a fresh assessment
of that transcript without repeating the simulation. Only a complete new rubric
replaces the saved partial one; marks from separate assessments are never combined.
Account export includes these sessions, and a progress reset deletes them.

With the pilot enabled, open any **EO → Tâche 2 → Sujets** detail page and
select the **headphones icon** just before Copy in the **Consigne** heading. Preparation
uses that exact publication, and Gemini plays its interlocutor using its
reviewed role, facts and `tu`/`vous` register. Personal notes and edited
questions are not included. Bookmarks for the old workshop or a published
topic’s rehearsal redirect to the corresponding simulation.

To enable the pilot for a test account:

1. In [Google AI Studio](https://aistudio.google.com/api-keys), create a key
   for a **dedicated project with Cloud Billing disabled**. Check the
   [model’s free tier](https://aistudio.google.com/docs/pricing#gemini-3.8-live)
   and availability in that project. Do not link a billing account or enable
   a paid tier to work around a quota error.
2. Set `GEMINI_API_KEY` for the conversation and EE1 grading, and a [Groq key](https://console.groq.com/keys)
   as `GROQ_API_KEY` for Groq bilans, **only in the server’s secret settings**. The voice pilot uses the existing
   `AI_PIN`; it needs neither an account-ID list nor an ElevenLabs API key.
   Restart the server. An operator must verify billing, age, region and the
   [provider’s terms](https://aistudio.google.com/docs/terms); Heureux does
   not check these. This is a private adult pilot in Canada and the US, not
   an opt-in for the general learner population. Share the PIN only with eligible
   testers trusted to authorize ElevenLabs generation too. Unset `GEMINI_API_KEY`
   to stop new Gemini calls, or only `GROQ_API_KEY` to stop new Groq bilans, without affecting narration.
3. Sign in as an approved tester, choose an EO2 topic under **Simulation**,
   then select **Commencer la séance**. Heureux checks the PIN before reading the prompt
   and never sends the PIN to Google. The reading and the exchange use separate,
   short-lived, single-use Google tokens. The exchange token is minted after
   microphone permission, so none of its lifetime is lost during preparation.
   The automatic review uses a separate, time-limited authorization bound to the
   same signed-in session and subject. During the exchange, microphone audio
   travels directly to Google, which may retain and review
   free-tier content. Use fictional details. No real recording is needed to
   run the automated tests.

**First listening check:** ask « Je n’ai que mon téléphone ; je peux quand même
venir samedi ? » (yes, for the park walk). Interrupt the reply with « Pardon,
je voulais dire mercredi soir. » The receptionist should change to the indoor
studio and explain the free camera loan **by reservation**, not promise a
booking. Listen for intelligible French, a clean interruption and a response
to the *correction*. An automated transport check cannot judge those.

### Tâche 3 · Expression d’un point de vue

Open **Expression → EO → Tâche 3 → Simulation** for a practice question, or
use the headphones on a subject page to practise that exact question. The same
opt-in voice pilot reads the question with the microphone off. Once the reading
finishes and the microphone is ready, speak for up to **4:30**, without preparation
or interviewer interruptions. The microphone stops at the deadline or when you
end the session. The Groq debrief evaluates the position, supporting reasons,
coherence and language of the transcribed intervention, not pronunciation.
The debrief keeps the question visible while the last captions arrive. Its
**Proposition** is a connected French rewrite of what the learner actually
argued, not a list of turns or an independent model answer. Paragraph breaks
are preserved when copying; reopening a saved report does not regenerate it.
The transcript remains read-only; practice scores are not official TCF results.
Saved sessions can be reopened or deleted; each oral task keeps its own history.

On a phone, allow microphone access for the site and keep the studio tab open.
During a session the studio shows the browser’s input label (when available) and
whether it receives sound. If the phone suspends audio, tap **Réactiver le son**.
If there is no input, try the same phrase without Bluetooth to isolate the headset route.
The input label and signal indicator stay on the device.

## French narration across the app

EE model answers, EO1 presentations, EO2 questions, vocabulary, learning examples,
notes, selected text and comprehension readers share one playback transport.
EO3 retains its native player and the same prepared recording on detail/practice
pages. Playback defaults to **0.85x**, adjustable from **0.75x to 2x**, with pitch
preserved. Pause, resume, restart and seeking do not generate audio or spend credits.
Reading starts only after a click and stops on card changes, hidden content,
navigation or another reader. French sources exclude English aids and UI labels.
The voice is AI-generated, not a human recording or pronunciation assessment.
Unavailable EO3 recordings show only a faint play icon, without an empty
narration card. Prepared recordings use a play/pause icon alongside completion.
New EO3 recordings include word timestamps for read-along highlighting in browsers
with the CSS Custom Highlight API. Highlighting follows playback and seeking
without altering the response text or annotations. Existing recordings are reused
unchanged; those without timestamps still play normally. On narrow screens the
player shows elapsed time only; total time remains visible above 600px.

Set the server environment (Render: **Environment**, not Build Command):

```text
ELEVENLABS_API_KEY=<server secret>
AI_PIN=<separate server-side generation PIN>
ELEVENLABS_VOICE_ID=kENkNtk0xyzG09WW40xE
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
EO3_AUDIO_ENABLED=True
EO3_AUDIO_SAMPLE_ENABLED=True
FRENCH_AUDIO_ENABLED=True
FRENCH_AUDIO_GENERATION_ENABLED=False
FRENCH_AUDIO_CHARACTER_BUDGET=0
DEEPL_API_KEY=<server secret>
DEEPL_TARGET_LANG=EN-GB
EE1_SIMULATION_MINUTES=12
EE2_SIMULATION_MINUTES=20
```

The selected voice ID is shown above, but code always uses the configured voice;
voice IDs are not secrets. Never put the API key in Git, chat, HTML or browser
code. Already prepared audio plays without a provider key. The narration UI and
sample switch default on; an explicit `False` disables them. No additional flag
activation is required when the server already has the voice and key configured.
`EE1_SIMULATION_MINUTES` and `EE2_SIMULATION_MINUTES` control the default
durations of new EE simulation attempts; existing attempts keep their original
deadlines. The defaults are 12 and 20 minutes.

**First audition: no shell or deployment command required.** Open **EO Tâche 3 →
Culture → Sujet 1** and click the faint play icon beside the progress badge.
Confirm the displayed voice and character count.
Only that canonical public answer can be generated before audition. The MP3
appears in the existing native player; click the play icon again to listen.
There is **one globally shared potentially billable sample attempt**, not one
per account, text edit or voice change. A failure or interrupted request does
not refund this authorization: inspect provider usage before allowing another attempt.
Other sample icons remain unavailable. No account-role change is required.

**Free-plan voice rejection:** only an exact structured ElevenLabs
`detail.code=free_users_not_allowed` (or legacy `detail.status` when `code` is
absent), on HTTP 401/403 with a complete error body of at most 4 KB, is classified
as a definitive pre-synthesis rejection. No raw provider message/key is saved
or displayed. That sample request becomes `plan_denied`, atomically releasing
the unbilled sample slot. Its conservative character reservation remains.
An administrator can configure a different, explicitly selected default voice
accessible to the account; reload the subject and confirm preparation again.
The app never switches voices, upgrades a plan or retries automatically.
Each denied voice is blocked across users/text/model changes, with at most
three such rejected voices globally. Upgrading access to the same previously
denied voice still needs explicit administrator review; it is not retried
merely because the browser reloads.

All other errors, malformed/truncated/oversized error bodies, HTTP 5xx, connection
failures and timeouts remain potentially billable and locked. A **legacy
`failed` row has no saved provider-code proof**: neither the account email nor
changing the configured voice can reclassify it. For recovery, a trusted
administrator must identify that exact request/fingerprint, obtain provider
confirmation that no synthesis/billing occurred, and explicitly authorize a
reviewed database recovery. Do not erase the row or clear the global claim from
a generic 401/403 message. No public recovery/reset endpoint is provided.

Do **not** append generation commands to Render's Build Command or startup.
If the earlier workaround was configured, restore the ordinary Build Command:

```bash
pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py deploy_database
```

The ordinary Gunicorn invocation automatically loads `gunicorn.conf.py`: worker
and graceful-shutdown timeouts are 210 seconds, above both the 180-second Groq
scoring timeout and the 90-second audio preparation timeout. Render needs no
start-command edit. One preparation occupies one
worker; no threads or queue daemon are required. Vercel serves cached playback
but rejects interactive paid preparation because its function runtime is not
configured for these bounded long requests.

Generation uses the official pinned ElevenLabs Python SDK with an explicitly
configured HTTPX client, not its permissive defaults: SDK and transport retries
are zero, redirects and environment proxies are disabled, and requests are
restricted to the fixed ElevenLabs HTTPS text-to-speech endpoint. The timeout
is 90 seconds; input is limited to 10,000 characters and streamed MP3 output to
8 MB. EO3 generation uses the fixed `/with-timestamps` endpoint, returning base64
MP3 audio and character alignment as JSON (up to 16 MB declared response size);
decoded audio retains the 8 MB limit.
A response hook bounds/sanitizes errors before the SDK can buffer them.
Compressed, incomplete, non-MP3 or oversized responses fail without automatic
retry. Installing the declared requirements is sufficient; no CLI OAuth or
local onboarding credential is used by the deployed server.

**Other recordings remain gated until the sample is approved.** After separate
approval, an operator can enable `FRENCH_AUDIO_GENERATION_ENABLED=True` and set a
finite positive `FRENCH_AUDIO_CHARACTER_BUDGET`. This is a **lifetime input
character ceiling**, including the sample and failed/uncertain attempts, not a
currency estimate or daily reset. Model pricing/multipliers still apply at
ElevenLabs. Web requests cannot raise or reset it. Each new recording then needs
its own explicit **Préparer cet enregistrement** cost confirmation. Ordinary
read clicks only look up the cache; a missing/error recording never silently
switches engines. **Voix de l’appareil** is an explicit alternative.

Every **new** ElevenLabs recording also requires the separate server-side
`AI_PIN`. Set it in Render's Environment settings; leaving it empty blocks
new generation, not playback of cached audio. The app requests it in a masked
dialog for each recording, including edited EO3 responses and general French
read-aloud. Audio cost confirmations use a download icon to continue to the PIN
step and a cross to cancel. The app does not remember the PIN or unlock later
requests. Incorrect attempts use the existing database-backed IP/account
throttles. The PIN is never
included in a URL, saved in an audio record, rendered in HTML or sent to ElevenLabs.
Operator generation commands also request it through a masked interactive terminal;
`--dry-run` and already-cached recordings need no PIN. Do not put the PIN in command
arguments or reuse an account login PIN.

The EO3 progress row also offers **cached-only continuous reading** (`≫`).
It starts at the current sujet, stays within the current theme and follows the
same publication order/deduplication as the sujet navigation. Missing, empty
or unavailable recordings are skipped. Saved sujet recordings remain playable
after voice changes and response edits. Earlier-text versions are labelled;
private takes remain accessible only to their owner. A saved public model can
also be played when an edited response has not been recorded yet.
One reusable audio element advances without reloading the page, with a now-playing
source link, pause, next and stop controls. Playback speed is adjustable from
0.5× to 2× (default 0.85×), retaining the chosen speed across tracks. The optional
repeat-two toggle plays each recording twice before advancing; it is not an
infinite loop. Changing speed does not restart the audio, and next skips straight
to the next available recording. These settings last until the page is reloaded.
It requests only cached media and a small read-only playlist; it never prepares
audio, calls ElevenLabs or asks for a
generation PIN. Playback does not mark subjects complete.

**Other read buttons use browser/system speech.** EO1, EO2, writing, vocabulary,
notes, selected text and comprehension reading use `SpeechSynthesis`, with French
voice selection, pause/resume, restart and speed controls. They do not look up or
prepare ElevenLabs recordings, even when saved audio or provider credentials exist.
Only the dedicated EO3 audio players use ElevenLabs recordings. Starting another
reader, changing a flashcard or leaving the page stops the previous reading.

The retained server-side audio service accepts only user-bound, signed, server-rendered French source
snapshots, valid for one hour, or a verified substring for selected text.
Reload after editing/expiry. It rejects arbitrary unsigned text, forged or
cross-account grants, over 32 sources, and over 10,000 combined characters.
Preparation requests are limited to 3 pending and 10 new requests per account
per 24 hours, with 100 pending/working requests globally. A transactional DB
reservation serializes paid calls and prevents duplicate billing. Failed or
ambiguous attempts are never automatically retried. Only the narrowly classified
sample rejection above releases its slot. Pending requests expire
after 24 hours but still occupy the queue until removed by a trusted operator.
Inspect provider usage and interrupted `working` rows before any manual
recovery; never reset `sample_claimed` or `reserved_characters` merely to hide
an error.

**Private text stays on device by default.** Private answers/overrides, EO1
presentations, notes and unrecognized selections use an explicitly local French
device voice, never a remote OS voice by default. If no local French voice is
available, the reader says so instead of uploading. It briefly waits for a
not-yet-loaded device voice list and allows retry after a French local voice is
enabled. General read controls have no paid-voice preparation or upload option.
Unrecognized/dynamically edited selections also remain device-only. Existing
private recordings remain owner-isolated and cascade on account deletion;
existing annotations, private responses and study state are unchanged.

MP3s persist in PostgreSQL/SQLite, not Render's ephemeral disk. Cache identity
includes exact text, voice, model, output format, synthesis settings and private
owner; EO3 additionally pins its canonical group. These immutable identities
still prevent duplicate generation, but are not a reason to discard paid audio.
EO3 playback first finds a saved take for the sujet and authorized owner, preferring
matching text and the current voice when available. Earlier versions stay available
and never paint word-by-word highlighting over changed text. Creating an updated
recording is a separate download-icon action with explicit credit confirmation and
a fresh PIN. The new configured voice applies to genuinely missing or explicitly
refreshed recordings, not ordinary playback. General read-aloud does not use this
recording cache.

The existing preparation journal binds earlier EO3 takes to their sujet and owner;
legacy audio without this evidence is reused only when its text/owner fingerprint
can still be verified. Operator `generate_eo3_audio` follows the same saved-sujet
policy; `--refresh --dry-run` explicitly estimates a current-text/current-voice
replacement before `--refresh --confirm-cost` and PIN authorization.
Authenticated same-origin media supports byte ranges,
uses identity encoding so gzip cannot corrupt offsets, and private audio is
never stored by the service worker. At 64 kbps, a four-minute recording is about
1.9 MB; budget database storage/backups accordingly. Tests use mocked providers
and silent WAV fixtures, not paid calls or voice-quality claims.

The PWA update banner rechecks the live worker when clicked. If another tab has
already activated it, the button reloads rather than becoming a no-op. An
unresponsive activation becomes retryable after 15 seconds, including after
returning to the tab; another tab's update never forcibly reloads ongoing work.

Optional trusted-operator recovery/preparation of one previously authorized
app-wide request uses the same durable claims and ceiling:

```bash
python manage.py prepare_french_audio --id <request-fingerprint> --dry-run
python manage.py prepare_french_audio --id <request-fingerprint> --confirm-cost
```

The legacy `generate_eo3_audio` command remains an explicit operator-only bulk
tool, separate from the web ceiling; do not run `--all` before separately
approving the corpus and cost.

## Account PINs

PINs accept 6–128 characters: letters (`A–Z`, `a–z`), digits, or a mix of both.
They are case-sensitive and do not allow spaces or punctuation. Registration,
login, PIN changes, recovery, and account confirmations use the same validation.
Existing six-digit PINs remain valid; no account migration or PIN reset is needed.

The account-menu initial avatar stays circular on mobile and desktop, in both
light and dark themes.

## Notes and highlights

On desktop, **Notes / Surlignages** stays centered between **Flouter** and the
view switcher. Folder filters and search actions sit directly below. On phones,
search, status filters, and note actions keep tap targets at least 44 px high.

Selected passages and translations offer separate **save without highlighting**
and **save and highlight** actions. Note-only saving leaves existing highlights
unchanged. If translation is unavailable, the translation dialog can still save
the selected French passage as a note without highlighting it; no translation
is invented or fetched from Google automatically. The **Nouvelle note** dialog
uses icon-only cancel, save and paste-and-close controls with accessible labels;
saving creates a note, not a highlight.

The selection toolbar's **Translate + note** button (`D`), between Translate and
Add to Notes, translates and saves in one background request without opening a
dialog or stopping playback, and highlights the original French passage. It reuses
existing coverage without changing saved highlights; partial overlaps use the same
revision-checked merge as the Highlight action. It captures the original
French passage and source context before sending; accepted requests can finish
both saves after navigating away. A spinner and toast report progress and completion.
This action requires `DEEPL_API_KEY`, accepts at most 2,000 selected characters,
and never falls back to another provider or saves a note when translation fails.
Exact retries reuse the existing note in the same user's source/range/context;
edited notes and identical text in other contexts are not overwritten. If a
highlight changed in another tab, the note remains saved and a separate message
reports the highlight failure; retrying does not duplicate the note.

Visible English text in bilingual EO2 questions and EO3 responses also offers
**Highlight**. English highlights persist separately across language switches
and reloads; revised translations use separate anchors, never the French ones.
French paragraph selections ignore hidden glosses instead of losing their
annotation tools. Notes and **Translate + note** continue to use French sources.

Saving a new selection can overwrite an older visible highlight at the exact same
source surface and character range, even if the stored text differs after an edit.
The surviving highlight keeps its identity and study flag; notes, hidden highlights,
other surfaces and other users are not overwritten. Revision checks still protect
against an outdated tab replacing a concurrent edit.

The EO2 and EO3 subject reset returns its status to **À commencer** and clears its
existing highlight paint, including after reloading or reopening practice.
Highlights are marked `hidden_on_source`, not deleted: their text, anchors,
dates and study flags remain in Notes and account exports. Notes themselves
are unchanged. Highlighting the same passage again creates a fresh visible
record without overwriting the hidden one. Private responses and practice/SRS
history remain intact; new practice or highlighting can start the subject again.

**Nouvelle note** always defaults to **Personnelles**, independently of the open
folder. Its optional group selector can explicitly assign an expression task.
Notes captured from EE/EO content keep their source task; contextual CE/CO notes
keep their comprehension folder. Creating a note opens its actual destination
folder, not an unrelated active filter. Migration 0057 corrects legacy standalone
notes that inherited a task despite having no quote, source path or source key;
it changes only their task assignment, retaining IDs, text, dates and study state.

EO3 selections can also carry a field identifier, checksum and relative UTF-16
offsets. These are anchor metadata, not saved response versions. An unchanged
field restores exactly even when both neighbouring paragraphs change. A quote
cannot escape its recorded field into another argument. Existing unscoped
selections acquire field metadata only when their offsets, quote and complete
saved contexts match the current publication. The ordinary conservative matcher
remains the fallback for older or stale clients; unprovable selections stay in
Notes rather than being placed by guesswork. See the staged rollout requirements
in `docs/eo3-editorial.md` before publishing adjacent-field rewrites.
The anchor column has a persistent database default for writes from preceding
workers during deployment; migration 0059 repairs the original 0058 schema.

Notes folders show 50 records per page and load only the active tab. Search and
tab totals cover all matching records; the study total is calculated before the
status filter. Flashcards use the full filtered selection, while the study queue
keeps all marked records in the folder. Page navigation works without JavaScript.
With JavaScript, study bookmarks, completion, pinning, editing, creation and
confirmed deletion save in the background. The active folder, filters, date
groups, counts and pagination are reconciled without reloading; emptied final
pages are clamped. Creating a note keeps the current view even when the chosen
group or active filters exclude it, and reports its saved group. French/English
blur, individual reveals, card/table mode and unsaved search/dialog input remain
intact. Different cards can save concurrently; stale refreshes cannot undo newer
actions. Failed writes retain the draft/state for retry; a failed list refresh
reports that the write already succeeded. Search bookmarks update in place,
including refilling capped results. Study-deck actions retain the queue position,
and edited personal titles update both faces. Source, folder and flashcard links
remain normal navigation; plain POST forms remain available without JavaScript.
Notes can be pinned with the pin action. Within the current folder and filters,
pinned notes appear first in an « Épinglées » section, still within the same
50-record pagination. With JavaScript, they use compact cards with a green dot
and pin icon; clicking a card or its open button shows the complete note in an
accessible dialog with the same note actions, including unpinning. The pin control
sits beside the note label, leaving the other actions in their existing column.
Pinning persists per learner, and unpinning restores the
note's original date position. Without JavaScript, full notes and pin forms
remain available. Apply migration 0067 before deploying this feature.
Throughout Heureux, form fields (including custom dropdowns) and modals have
rounded corners without pill-shaped ends. Icon buttons are circular and text
buttons are pill-shaped, including inside cards, toolbars, and dialogs.
Standard text buttons, menus, and simulation actions share compact padding.
Simulation actions retain a 44 px minimum height on touch devices. Sign-in,
registration, and signed-in pages load the same versioned stylesheet.
The shared audio PIN dialog uses compact cancel (×) and confirm (✓) controls.
Note and translation pop-ups also round the DeepL and Google **G** action links.
Translate works with touch taps as well as mouse and keyboard
activation. When `DEEPL_API_KEY` is set, the panel translates through DeepL on the
server first (`DEEPL_TARGET_LANG`, default `EN-GB`; keys ending in `:fx` use the
free API), then falls back to the browser's on-device engine. Without DeepL, the
on-device engine runs first and the optional `TRANSLATION_API_URL`
(LibreTranslate-compatible) service is the fallback. If nothing works, the panel
suggests **Open DeepL**. The DeepL link reuses one tab across translations (the
site sends `Cross-Origin-Opener-Policy: same-origin-allow-popups` for this);
Google Translate opens a new tab each time because Google severs the opener.
Selected text goes to DeepL only via the configured key or when a link is opened.
The shared `study/shared/partials/pagination.html` pager accepts a Django `page_obj`,
`page_links` (`number` and `url`), previous/next URLs, and an optional accessible label.

Vocabulary theme, category and comprehension-test pages share a compact,
collapsible guided-lots component with completed/active counts. The vocabulary
stays full-width, and the lot links work with keyboard controls or without JavaScript.

## EE writing formulations

`/expression/ecrite/tache-1/formulations/` and
`/expression/ecrite/tache-3/formulations/` are the EE writing toolkits. Each
catalogue organizes formulations into writing functions and subject themes. EE1
covers practical messages: opening and closing, setting context, invitations,
descriptions, practical information, advice, requests, impressions and complaints.
EE3 covers titles, neutral synthesis, stance, opposition, concession, conditions,
arguments, examples, consequences and conclusions.

The catalogue root uses two progress tables: one for writing functions and one for
themes. Each top-level row expands in place to reveal its individual lessons and
completion controls. EE3 theme rows also expose their vocabulary reference. A lesson opens one
focused page containing only that formulation, its English meaning, usage and
grammar guidance, every distinct relevant model excerpt found in the effective
corpus, and a transfer exercise for applying it to a different prompt. Search,
whole-subdivision browsing and opt-in recall
practice remain available as separate views.

The EE3 synthesis subdivision includes a response-grounded reference for reporting
verbs such as `mettre en avant`, `indiquer` and `mettre en garde contre`. Every
EE3 theme has a substantial response-grounded vocabulary reference (at least 24
entries) organized into notions, collocations, benefits, risks, conditions,
solutions and argument mechanisms. Every EE1 theme also exposes a concise
response-grounded vocabulary reference with common words and phrases, English
meanings, French usage guidance and verbatim examples from its model responses.
Every entry includes an English meaning and all distinct useful complete-sentence
examples supported by the effective Partie 1 and Partie 2 responses. Each expression
has a private completion checkmark, and the page header reports learned entries
against the category total. Learned status is the learner's own assessment of being
able to reproduce and adapt the formulation or expression, not an exam score.

The file-backed curricula live in
`study/content/expression/ee/tache_1/formulations.json` and
`study/content/expression/ee/tache_3/formulations.json`. The EE1 vocabulary reference lives in
`study/content/expression/ee/tache_1/formulation_vocabulary.json`.
`study/expression/ee/formulations/catalogue.py` and `study/expression/ee/formulations/vocabulary.py` validate
their task-specific categories, complete effective-source coverage and verbatim
example provenance. Frames and teaching guidance are editorial adaptations, not
quotations. Examples refer to the bundled reference corpus, not live summaries of
edited or personal answers. Source revisions must keep the evidence current, and
workers must restart after catalogue changes.

Bundled content is scoped by skill and task:

```text
study/content/
  comprehension/
    ce/                       # Written tests and their vocabulary
    co/                       # Listening tests
    tests.json                # Shared test catalogue; source basenames stay stable
  expression/
    eo/tache_{1,2,3}/
    ee/tache_{1,2,3}/
  learning/                   # Cross-skill lessons and preservation manifests
  sections.json               # Shared exam/task catalogue
```

EO3's `themes/<current-theme>/` folders follow the nine current display themes.
Each owns `responses.json`, `hints.json`, `prompt_notes.json`, and
`translations.en.json`; a source identity such as `culture-p3` can therefore live
under `societe/` without changing saved notes or model keys. Strict readers reject
missing groups, duplicate ownership, or a theme folder inconsistent with taxonomy.
`sources/` holds the historical source catalogue and phrase/family indexes;
`sources/archive/` preserves original Notion response batches under their original
seven theme names, retired vocabulary decks, and layout history. Archives are
provenance, not competing current models. There is no old-path compatibility tree.

EO3 subject navigation uses `study/content/expression/eo/tache_3/subject_taxonomy.json`:
9 display themes and 61 specific subthemes cover all 131 semantic groups and
167 exact formulations. Every equivalent formulation shares its group's display
category. In the Sujets directory, grey dividers mark the subthemes in both
Cards and Table views. These labels are presentation-only: the seven source/vocabulary themes,
prompt numbers, ownership, URLs, answers and saved learner state remain unchanged.
Source-theme names accompany original prompt numbers; progress counts unique
responses in both the deduplicated and all-formulations views. The strict,
immutable taxonomy is process-cached by `study/catalogue/registry.py`; restart workers after
editing it (tests use `clear_catalogue_cache()`).

Lesson completion keys use `formulation:ee1:v1:<slug>` and
`formulation:ee3:v1:<slug>`. Vocabulary-reference completion keys use
`formulation-language:ee<tache>:v1:<category>:<stable-expression-id>`. A note or
highlight on a formulation lesson marks that lesson as started (`En cours`) without
marking it learned; deleting the last annotation returns it to `À apprendre`.
Materially
changing a learning target requires a new identifier. Removed EE1 and EE3
vocabulary collection URLs return 404; there is no legacy vocabulary interface.

The retired EE1 and EE3 vocabulary source files, parsers, imports and page renderers
are deleted. Existing database rows are deactivated and excluded without a
data-deletion migration, so cards, schedules, reviews and annotations remain intact.
Phrases still owned by another active task remain available there.

EO Tâche 3 vocabulary is also retired: its navigation, themed collections,
subject-side vocabulary and vocabulary practice are no longer available.
Historical phrases, cards, schedules, reviews, notes and highlights are retained;
shared expressions remain available in other active tasks. Pistes, audio, editing
and subject completion remain available on the response pages.
The original EO3 vocabulary sources remain archival evidence, but imports no longer
load its themed banks or provision retired vocabulary cards. Other tasks keep their
existing vocabulary features.

EE1 keeps one authored repository-default response per canonical subject in
`study/content/expression/ee/tache_1/responses/`. Imports update that reference corpus without
deleting learner-authored responses, overrides, highlights or completion history.

## Subject pistes and oral equivalence

EO task 2 provides reviewed **eight-question conversations** for all 164 semantic
situations and their 348 published prompts. The file-backed corpus in
`study/content/expression/eo/tache_2/dialogues/` uses priority-ordered topic headings,
response-grounded follow-ups included in the eight,
and a separate greeting and final thanks. A short English **Comprendre la consigne** note
identifies the roles, objective, chosen tu/vous register and contextual traps;
substantively different publications can have their own note.
Examiner replies in the source files are editorial scaffolding only: they help
review realism and consistency, but are never shown or seeded into learner
responses. Subject pages, practice and the editor display questions only.
English conditional cues explain when a follow-up fits the actual reply.
This is an NCLC 7/8 preparation target, not a score guarantee or a fixed script:
learners should adapt to the actual examiner's reply.

The current **Travail & emploi** theme has 13 models for 28 publications;
**École & études** has 11 models for 19 publications. Their routes distinguish
joining a company, hearing about a friend's first day, preparing with a recruiter
and asking a friend for interview advice. School enquiries distinguish a teacher,
an administrator and another parent's experience. Practical follow-ups concern
the actual task, course, activity or difficulty named, rather than a required
scripted answer. Earlier published layouts remain in the existing EO2 history,
so unchanged questions can retain annotations when they move; personal questions
and private prompt notes are never replaced by the revised public models.

**EO2 question language.** The nine initial themes (arrival, housing, everyday
services, work, school, outings, childcare/pet care, volunteering and tourist
accommodation) support saved French/English question views: 75 models and 600
questions. French is the default. The language control remembers an explicit
choice across subjects; clicking a question number overrides only that row.
Individual overrides reset on navigation. Greetings, thanks, headings and
consignes remain French. Audio still reads the canonical French questions.

English is served only from exact-text DeepL records in
`study/content/expression/eo/tache_2/translations/questions.en.json`. Toggling never calls a
translation provider or changes completion/practice status. French annotation
text and existing highlights remain intact; English glosses are not French
annotation sources. Modified private questions are never uploaded automatically:
only questions matching saved public text can show cached English. Missing,
stale or invalid translations are reported explicitly, with unavailable controls
disabled rather than guessed translations.

Preparation is an operator-only, resumable command. Set `DEEPL_API_KEY` locally
(never commit it); `DEEPL_TARGET_LANG` defaults to `EN-GB`. Inspect the dry run,
then replace `N` with its exact current source-character count:

```bash
python manage.py prepare_eo2_translations --dry-run
python manage.py prepare_eo2_translations --prepare --confirm-characters N
python manage.py prepare_eo2_translations --check
```

Only public French questions and public role-play context are sent to DeepL.
Preparation checks the provider allowance first, skips exact cached questions,
and saves each completed model atomically. After an interrupted request, inspect
the new dry run before resuming; there is no automatic billable retry.
Review the generated English before publishing and record `reviewed_at` only
after that review. New preparation clears this stamp. Reviewed corrections retain
the original DeepL text in `deepl_english` with a short `review_note`.
An empty manifest means translations have not been prepared; the application
does not substitute invented English.

**Transports & mobilité** has 11 models for 26 publications; **Voyages & circuits**
has 15 models for 32 publications. Their routes distinguish network information
from a resident's advice, buying from renting, and occasional from neighbourly
carpooling. Travel questions follow the actual purpose: an agency proposal,
a returned traveller's experience, a future project or planning together with
a friend. Timings, activity seasons, costs and relances stay consistent with the
replies; all earlier published layouts remain available for annotation recovery.

`study/expression/eo/tache_2/dialogues.py` rejects incomplete coverage, malformed dialogues,
duplicate questions, noncontiguous headings and invalid follow-up references.
Subject pages, practice and the personal editor use the same current model.
Personal questions remain private and take precedence; the editor also preserves
editable greetings and thanks. The English consigne explanation is collapsed by
default on the subject and practice front; expanding it reveals **Modifier la
note**, which opens the same personal editor. A personal note stays private and
can be cleared to restore the publication's default note. EO2 uses the generic
response's otherwise unused `nuance` section
for this explanation. Note-only changes preserve the French questions, thematic
layout and their highlights; the English note is not read aloud in French.
Existing private prepared replies remain stored
and exportable, but are not rendered or discarded when saving questions.
The original batches, import models, vocabulary
evidence, semantic memberships and learner progress are unchanged.
EO2 and EO3 public responses now have content-independent annotation identities.
An editorial push replaces only the current authored text: unchanged selections
are relocated by their exact quote and unambiguous saved context, including on
practice fronts and backs. Notes, highlight IDs, personal responses and progress
are retained. Removed or ambiguous selections stay in Notes rather than being
painted onto unrelated replacement text. Existing published identifiers have a
fixed, identifier-only transition bridge; future edits need no response snapshots,
version inventory or new migration identifiers. Older EO2 geographic corrections
retain their existing specialized recovery. Restart workers
after editing the corpus; deployment imports validate the complete corpus without
overwriting personal responses.

The preparation guidance was checked against FEI's
[TCF Canada description](https://www.france-education-international.fr/test/tcf-canada),
[September 2026 candidate handbook, version Q](https://www.france-education-international.fr/document/manuelcandidattoutes20dc3a9clinaisonsi)
(pages 19 and 21), and
[oral assessment criteria](https://www.france-education-international.fr/article/evaluation-epreuves-tcf).
Task 2 allows two minutes of preparation followed by three minutes thirty of
interaction. The objective is obtaining relevant everyday information in the
assigned roles, not reciting a monologue. Assessment considers linguistic control,
interaction/coherence and appropriateness to the situation. Eight questions and
a varied mix of question forms are teaching choices, not official quotas or
mandatory inversion rules. Follow the actual replies and the examiner's timing.
The handbook explicitly warns against reciting memorized texts.

The Canadian job-search scenario distinguishes work-authorization checks with
IRCC from [Service Canada's social insurance number procedure](https://www.canada.ca/en/employment-social-development/services/sin/apply.html).
Required documents depend on the learner's status; a friend's examples are not
legal guarantees or a substitute for the current official requirements.

[IRCC's official conversion](https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/documents/language-test.html)
maps the **whole oral test** score of 10–11/20 to NCLC 7 and 12–13/20 to NCLC 8.
No single task or fixed set of questions guarantees either level.

EO task 2 subject pages show bilingual **Pistes** (hints): short French information targets
with English meanings, not ready-made questions. The editorial lists in
`study/content/expression/eo/tache_2/subjects/hints.json` cover every semantic group, including
singletons; every equivalent publication shares the same immutable list, whether
the current response is a model or personal. Each group needs 5–10 unique cues,
with both languages and at most 100 characters per language. The loader rejects
missing/unknown groups and malformed entries instead of substituting generic hints.
Pistes are file-backed, require no migration, and never rewrite responses or progress.

EO task 2 separates **Services du quotidien & entraide**, **Garde d'enfants &
d'animaux**, and **Bénévolat & vie associative**. Classification follows the
candidate's objective: an animal-protection association is volunteering, watching
a friend's apartment is practical help, and choosing outings for visitors belongs
to **Sorties, visites & bonnes adresses**. Equivalent consignes always move together. Existing
memory numbers remain stable; the care and volunteering collections are Mémoires
12 and 13. Each theme retains 52 reusable questions and 45 vocabulary entries.
Moved questions retain their original identity through `legacy_memory_number`,
and moved vocabulary retains its phrase ID, preserving learned state. Exact
pre-split study collections are kept in `question_bank_history/`.

The former **Voyages & vacances** theme is likewise split by objective:
**Voyages & circuits** (Mémoire 7) covers whole trips, preparation and travel
experiences; **Escapades & tourisme régional** (Mémoire 14) covers weekend
getaways, regional visits and day excursions; **Hébergements touristiques**
(Mémoire 15) covers hotels, guesthouses, campsites and holiday-house bookings,
not permanent housing.
A tourist-office enquiry follows its subject, not the employee's workplace.
Travel-blog creation belongs to **Culture, lectures & médias**, and Canadian
weekend leisure habits belong to **Loisirs, clubs & jeux**; discovering the
city with friends belongs to **Sorties, visites & bonnes adresses**.
All equivalent publications move together without changing their consignes,
dialogues or Pistes. The original 52 Mémoire 7 questions and 45 travel vocabulary
entries remain available with their exact learning identities; the three
collections each contain 52 questions and 45 vocabulary entries. Exact pre-split
snapshots are stored in `question_bank_history/travel.json` and
`question_bank_history/travel_vocabulary.json`.

The earlier joint culture reorganization retains **Culture, lectures & médias**
(Mémoire 16), including film/book discussions, libraries and article preparation.
Its exact source snapshots remain in `question_bank_history/culture.json` and
`question_bank_history/culture_vocabulary.json`.

The remaining two broad collections are now separated into **Sorties, visites &
bonnes adresses** (Mémoire 9), **Cours & ateliers** (Mémoire 10), **Cinéma,
spectacles & festivals** (Mémoire 17), and **Loisirs, clubs & jeux** (Mémoire 18).
Classify by the candidate's dominant objective: planning local visits and meals,
learning a skill, attending a screening/performance, or participating in leisure
activities. A television/bookshop game is participation, not media consumption;
an unspecified artistic or gardening activity does not automatically imply
lessons. Occupying visiting nephews includes games and activities at home, so it
belongs with leisure activities rather than venue-based outings.
All 61 affected publications move with their equivalents, retaining their 30
semantic identities, reviewed dialogues and Pistes. Existing slugs and Mémoires
9 and 10 stay stable; 17 and 18 are appended without renumbering other collections.
Every one of the previous 104 questions and 90 vocabulary dictionaries survives
unchanged, including its original learning identity across multiple moves.
The four collections each contain 52 questions and 45 vocabulary entries.
Their exact previous layouts are archived in `question_bank_history/leisure.json`
and `question_bank_history/leisure_vocabulary.json`; whole-section annotation
offsets are not projected onto reorganized text. The corpus now has 18 themes,
936 reusable questions, 810 vocabulary entries and 54 vocabulary lots; its
348 source publications and 164 semantic responses are unchanged.

**Travail & emploi** and **Logement & déménagement** remain single themes.
Retirement and promotion parties belong to **Fêtes & célébrations**; furniture
delivery and help transporting heavy objects without an established household
move belong to **Services du quotidien & entraide**. Renting out one's own home
for income remains a housing question, and working in an association remains
employment unless volunteering is specified. These boundary corrections move
all equivalents and their source-question memory links, without changing
dialogues, learning identities, reusable question banks or vocabulary collections.

The EO2 sidebar retains completion, personalisation and individual practice controls;
practice statistics and vocabulary are no longer displayed there. Vocabulary and
its saved practice data remain available in their existing dedicated views.

EO task 3 provides a collapsed English **Comprendre la consigne** explanation on
the subject and practice front,
using the same disclosure style as EO2. The 131 source-pinned notes in
`study/content/expression/eo/tache_3/themes/<current-theme>/prompt_notes.json` cover all 167 publications. Each explains
the exact question, useful terms, concrete discussion angles and scope traps
without imposing a position or inventing a learner's biography. They remain
editorial guidance, not personal answer content, and are excluded from annotation
offsets and French read-aloud text. EO2's editable notes and all EE surfaces remain
unchanged. The bilingual plans in `study/content/expression/eo/tache_3/themes/<current-theme>/hints.json` appear as
subject-specific **Pistes** on EO3 detail pages and practice backs: introduction
and position, three arguments with examples, nuance and conclusion. English and
French cues use the same presentation as EO2. These shared model plans remain
independent of personal answers and complement **Comprendre la consigne**.
The generic **Expressions liées** block is no longer shown on these detail pages.
Its legacy sidebar markup stays hidden to keep historical annotation offsets
exact; expressions, study lots and saved progress remain available in their
existing study collections.

Reviewed EO task 3 defaults live in `study/content/expression/eo/tache_3/themes/<current-theme>/responses.json`, with
complete theme coverage and every equivalent source question pinned. They use
the existing introduction, three supported arguments, nuance and conclusion
fields. Reviewed practice backs include the supports as well as the claims.
Original published Markdown and vocabulary evidence remain unchanged; active
personal versions still take precedence. Reviewed public defaults keep stable
annotation keys across edits; selections are restored only by exact quotes and
unambiguous saved context, never by replaying old offsets. See the
[oral-task-3 editorial standard](docs/eo3-editorial.md) for timing, grouping,
preservation and revision criteria.

EO3 editing updates one current response per subject and learner, starting with
the reviewed model. Saving again updates the same row; it does not create a new
full-response history snapshot. Edited responses keep the complete introduction,
arguments, examples, nuance and conclusion in both detail and practice. Their
annotation identity and argument field identities stay stable, so unchanged
highlights and quoted notes remain attached. Already disconnected selections can
be recovered from exact current-model anchors or provable, learner-owned legacy
data; unknown namespaces are not guessed. Removed or ambiguous passages remain
saved in Notes rather than being highlighted elsewhere. Reset-hidden highlights
stay hidden. Existing recovery records are retained, not multiplied or deleted.
Private edits never use the public model's narration or silently opt into external
reading. EO2 and EE response-history behavior is unchanged.
Each saved private argument also retains its small identity marker independently
of later public-model rewrites; this is metadata, not another response version.
EO3 subject pages have compact, icon-only **Copier le sujet** and **Copier la réponse**
controls on the prompt header and the first response card, matching the EE controls.
Copying a response uses the learner's current text, with French
paragraphs for the introduction, developed arguments, nuance and conclusion;
hints, annotations and interface labels are not included.

EE task 1 also provides **Pistes** for Invitations & fêtes, Sorties & visites,
Accueillir un invité, Voyages & vacances, Ville & quartier, Logement &
déménagement, and Transports & orientation. The 44 canonical lists in
`study/content/expression/ee/tache_1/hints.json` cover all 96 equivalent publications.
They summarize reviewed current responses, including authorized customizations,
without publishing account identifiers or private contact details. Each list has
5–8 bilingual cues, at most 110 characters per language per cue and 75 French
words in total. These are shared editorial snapshots, not live summaries of an
account's latest answer. The cache contains no learner state. The card follows
progression without a separate header shortcut and stays outside response
annotation roots; other writing themes/tasks remain unchanged.

EE task 1 model pencils edit that response in place in the learner's account,
using its existing model identity rather than creating a separate personal copy.
Repeated saves keep one current response. An existing personal answer replaces
its unedited main-model counterpart in the display and directory counts; neither
its text nor separately edited alternatives are deleted. Unchanged highlights
and quoted notes are carried across targeted edits, including former model
highlights on an existing personal answer. Removed or ambiguous selections stay
in Notes instead of being painted onto unrelated text. No response-history
archive is created. Shared source models, other accounts, and EE2/EE3 editing
behavior are unchanged.

EO task 2 and task 3 use editorial `semantic_groups.json` partitions, including
singletons. A shared answer or question-body hash is **not** proof of equivalence.
The importer rejects missing, incomplete, duplicate or cross-task memberships.
The manifest canonical retains identity; directories display the first publication
in their own order and search all publications before grouping and limiting.

Each prompt keeps its matching model text, questions and vocabulary. Detail pages
and practice show one current response: the learner's active personal response,
or the published model when there is no personal override. There is no version
chooser or oral history page; former history URLs and version-selection parameters
return 404. Saved personal data, schedules, review logs and recovery snapshots remain
stored and available in account exports. Resetting selects the published model
without deleting work. Annotations remain available in Notes rather than being
replayed on a different response text.

An old response's ambiguous shared state belongs only to the corrected group
containing its original canonical key. Occurrence-provenanced annotations and
personal work follow their source prompt. Split vocabulary decks retain original
source IDs where available, otherwise use stable derived IDs with fresh progress.
Imports retain original response/card/log IDs and never fan out old completion to
all previously grouped prompts. Schedule projection snapshots the target and donor
states first and runs once per membership revision, excluding rationale changes.
Historical previous reviews remain inspectable but cannot undo a schedule already
projected into another group, including a surviving canonical card's old reviews.
The importer locks affected review sessions before cards, archives and clears
stale Undo pointers without deleting their logs, and records each projected
card's existing review-log high-water ID. Undo cannot cross that boundary.
Timestamp ties and unchanged imports do not invalidate genuinely later reviews,
including reviews written by an old worker during application replacement.

**Deployment gate:** apply migrations and import both complete manifests before
serving the new application. Render builds call `deploy_database`
(migrations first, then fingerprinted import); Procfile releases do the same.
Vercel builds only run `manage.py check` and never touch the database.
Do not use `[skip db]` for this rollout. For a manual deployment run
`python manage.py deploy_database --force`, then restart workers. Do not regenerate
manifests from body hashes or replace the immutable original source files.
The additive oral columns keep database defaults as well as Python defaults,
so workers using the pre-upgrade ORM can finish inserts during replacement.

## Runtime efficiency

- `study/catalogue/registry.py` shares immutable bundled expression content across requests.
  Restart workers after content changes; learner progress and database querysets
  are never cached there. Custom-path parsers and content imports still validate
  their inputs directly.
  EO3 models, prompt notes, speaking plans and taxonomy share one source parse,
  retaining only immutable prompt/group identities rather than source bodies.
  Detail progress groups repeated oral highlight identities in SQL while retaining
  their earliest/latest activity and resolving ownership with the same priority.
- Subject directories reuse one collection/group/row component and render each
  publication once, with card and table presentations of the same elements.
  Open an EO Tâche 3 theme to see one table. Subthemes are labeled row groups,
  not additional disclosures. Each level counts unique responses for progress.
  Theme-specific labels in `study/content/expression/eo/tache_3/sources/subject_family_labels.json`
  clarify the existing families without changing memberships or saved progress.
  EO/EE subject directories and subject-only searches default to **Dédupliquer**,
  keeping the first displayed occurrence of each equivalent group. The toggle or
  `?deduplicate=0` shows every publication. Search and subject links preserve the
  chosen mode, including previous/next navigation and its within-theme counter.
  Opening an equivalent publication keeps its own text and selected response,
  while its navigation position refers to the shared group when deduplicated.
  The EO2, EO3, and EE1–3 Sujets directories let you filter by theme and study
  progress. Choose **Statut → Favoris** to see your bookmarked subjects from
  any progress state; bookmarking a subject does not change its progress.
  Bookmarks and completion checkboxes save without reloading. You can mark
  several subjects in succession; equivalent publications, progress counts,
  and filtered results update in place. A failed save restores that marker.
  Sort alphabetically or put in-progress subjects first.
  The filter bar is centered; on phones the action buttons sit centered below
  the fields. The three dropdowns support arrow keys, Enter to choose, and Escape
  to close without changing the selection. Use **Appliquer les filtres** (✓)
  to apply all three choices together, or **Réinitialiser les filtres** (↺)
  to clear them without changing deduplication.
  Filters and sorting are shareable in the directory URL; keyword search still
  searches the whole task, including alternative formulations.
  The removed EO Tâche 3 theme/family and
  practice-overview URLs have no routes and return 404, without redirects.
  Individual practice sessions, study content, and saved progress remain.
  Oral and written completion controls share one JavaScript controller.
  EE1/EE2 response cards have per-account Edit controls and Delete controls on
  alternatives only, with confirmation. The main response cannot be deleted
  through these controls. Migration `0054` stores private model-version edits and
  deletions without changing shared content; equivalent prompts share them.
  Removing a version preserves the remaining copy and annotation identifiers.
- Vocabulary listings start in table view and remember their card/table choice
  separately from subject and note listings. Study/review sessions retain their
  flashcard behavior. Selecting a guided lot opens its entries in table view;
  a separate practice action starts that lot's available review cards.
- Subject progress filters highlight candidates before transferring rows to Python.
  Existing source-key and URL parsers remain the final matching authority; batching
  keeps larger requests within database parameter limits.
- Notes and highlights have independent ascending/descending date controls within
  each relative-date period. Sorting uses capture time, preserves the period order
  and filters, and runs before pagination; it never changes saved annotations.
- Course exposure checks use an indexed, derived projection of allocated item
  identities, not scored progress or answers. The first access indexes all missing
  attempts in batches; subsequent access processes only newly unindexed attempts.
  Original snapshots and events remain authoritative. Native deletion cascades on
  the projection tables must be preserved by future migrations.

Course attempt/production histories and same-lesson scored-guidance reconstruction
remain history-dependent; the exposure optimization does not truncate or cap them.

## Project structure

| Path                                | Responsibility                                               |
| ----------------------------------- | ------------------------------------------------------------ |
| `config/`                           | Django settings, root URLs, and deployment entry points      |
| `study/models.py`                   | Persistent study, progress, and account data                 |
| `study/accounts/services.py`         | Account provisioning, recovery, and login throttling         |
| `study/catalogue/loader.py`           | Pure parsing and validation of bundled study content         |
| `study/catalogue/registry.py`                | Shared immutable expression catalogues and lookup indexes    |
| `study/expression/ee/formulations/catalogue.py`          | Validated EE1/EE3 writing frames, evidence and categories    |
| `study/learning/catalogue.py`         | Validation and cached loading for the Learn curriculum        |
| `study/learning/courses.py`           | Typed original course and benchmark coverage contracts       |
| `study/learning/practice.py`          | Server-side selection, grading, exposure and delayed review  |
| `study/review/presentation.py`        | Review scope parsing and card response payloads              |
| `study/expression/personalization.py` | Canonical and personalized response resolution               |
| `study/views/`                      | HTTP request handlers and shared view helpers                |
| `study/templates/study/<feature>/` | Domain-owned pages and partials; shared fragments in `shared/partials/` |
| `study/static/study/`               | Versioned CSS, JavaScript, icons, and images                 |
| `study/content/`                    | Source-controlled content imported into the database         |
| `study/content/learning/`           | Source-controlled lessons rendered by the Learn experience   |
| `templates/`                        | Project-wide shell, error, PWA, and service-worker templates |

The preserved reference library is loaded from
`study/content/learning/curriculum.json`. Original course lessons are complete
JSON objects under `study/content/learning/courses/<level>/`. Both catalogs are
validated and cached per process; restart the app after changing content.
Lesson-only edits do not invalidate the database-content import fingerprint;
the importer still checks all imported content, its code, and schema inputs.
Keep lesson IDs, section IDs and slugs stable to preserve saved progress,
annotation anchors and links. `/apprendre/` defaults to the original course
when installed; `?scope=reference` and all old detail URLs retain the library.
An absent course directory falls back to reference reading, not an empty replacement.

Course summaries, objectives and the practice link sit in a right-hand sidebar on
wide screens and above the teaching on smaller screens. Use explicit backticks
for French snippets inside English explanations; the existing inline renderer
marks them as French and gives them a distinct style. Do not automatically style
ambiguous words such as English "on". Plain-text searches ignore those backticks.
Apply this convention throughout A1–B2 and C1-preparation teaching, including
mixed-language section headings, example notes, correction explanations and
production instructions/rubrics. Leave already-French examples and translations
alone unless an English explanation contains a genuine French mention. The
all-course formatting pass preserves wording, identities and every exercise object.
Assessment versions ignore these teaching-only delimiters, so completed checks
and delayed reviews remain current. Previously stored attempts are not rewritten.

The course contains 33 A1, 36 A2, 26 B1 and 25 B2 lessons, with exact
coverage mappings for all 479 public benchmark topics, plus nine C1-oriented
preparation lessons. The teaching-depth follow-up enriched 75 existing lessons
after reading all 479 public teaching bodies: 478 comparisons are complete and
one compound-order variant remains explicitly unassessed. Its 2,513 controlled items and contextual self-review tasks
do not replace independent four-skill assessment. See the
[implementation record](docs/apprendre-rebuild-plan.md) for scope and limitations.

See [the course contract](docs/apprendre-implementation-contract.md) for the
lesson, coverage and depth-report schemas. The immutable `course_manifest.json`
records published identities, sources and preparation links. Validate authored content before deployment:

```bash
python manage.py validate_courses
python manage.py validate_courses --coverage
python manage.py validate_courses --coverage --depth
python manage.py test study.tests.test_course_bundle study.tests.test_course_depth study.tests.test_course_platform study.tests.test_learning
```

Reading completion is self-declared and separate from controlled grammar results.
Practice reveals feedback on request; checks and reviews grade first submitted
answers on the server using frozen item snapshots. The bounded criterion is
80% overall and 75% text accuracy. Review opens seven days after the first
successful check for that content version, including a clearly labelled
rehearsed success after a failure. Previously presented items, even from abandoned
sessions, cannot become fresh evidence through a retry or feedback edit.
Bank exhaustion permits rehearsal, not a false independent-mastery claim.
Open production is saved for model/rubric self-review, never automatically scored.

The separate practice page offers section/item guidance, not a mastery score.
Learning prioritizes recent incorrect or blank first answers, then hint-supported
answers, then untested items, using completed sessions only. It spreads equally
prioritized sections and prefers unseen practice items within the chosen focus;
revisiting a known weakness may deliberately rehearse an old question.
Checks/reviews spread eligible sections while preserving their bounded size,
text-answer quota and fresh-bank preference. Frozen session scope lists omitted
sections and those without eligible items; a short sample is not full coverage.
Section feedback uses only completed checks/reviews, counts the latest first
answer per unchanged item, and labels rehearsed evidence. Unchanged item versions
can inform guidance after teaching edits, explicitly labelled as older evidence;
new or changed items remain untested, and earlier results are never rewritten.

Answer normalization preserves accents and internal punctuation, while allowing
case, typographic apostrophes, whitespace and optional terminal `. ! ? …`.
Items testing capitalization or terminal punctuation can explicitly set
`case_sensitive` or `terminal_punctuation_sensitive` to `true`.
Account export format 11 includes reading, session history, course productions,
saved Gemini Live sessions, private writing-response overrides, and annotation
completion/source metadata; unfinished and abandoned session answer keys remain
hidden. Confirmed progress reset removes course history, productions and saved
Gemini Live sessions, preserving notes and highlights.
Account deletion cascades all owned course data. No practice percentage converts
to an official CEFR, TCF or NCLC score.

For reference-library provenance only,
`source_type` accepts `pdf`, `notion`, `mixed`, or `editorial-gap-fill`;
source-backed lessons must retain their source labels. Labels record provenance,
not proof that every item in a source is covered.

## Naming conventions

- Python modules use `snake_case` and describe one responsibility. Service,
  loader, presentation, and helper modules carry those roles in their names.
- Browser assets use `kebab-case`; names describe behavior rather than an
  implementation detail or one third-party provider.
- Reusable templates live in their feature's `partials/` directory; genuinely
  cross-feature fragments live in `study/shared/partials/`, without underscore prefixes.
- Collection cards and native tables reuse `progress_card.html` and `table.html`
  in that shared directory. Feature partials extend those shells for their own
  content, attributes and rows; callers retain URL resolution and collection
  loops. Keep existing DOM hooks and CSRF context when extracting a component.
- Numbered task directories use `tache_<number>`. Numbered content packs use
  explicit suffixes such as `_1` or `_01`, according to the source series.
- Database content keys, source IDs, and URL names are stable identifiers. File
  organization may change, but those identifiers must not be renamed.
