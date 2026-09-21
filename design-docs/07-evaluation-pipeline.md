# 07 - Evaluation pipeline

## What

This feature built the part of ScholarLens that grades the agent. One command,
`python -m app.evaluation`, takes 25 made-up students whose correct answers a
human decided in advance, sends each one to the eligibility agent three times,
and compares what the agent said with what it should have said. It prints a
scorecard (how often the status was right, how often the quoted rule was the
right rule, how often the agent invented something) and appends the full result
of the run to a file so a later run can be compared with it.

Before this, the only way to know whether the agent was any good was to ask it a
few questions and see whether the answers felt right. After this, "is it good?"
has numbers, and "did that change make it better or worse?" has a before and an
after.

It is the measuring half of the project. Features 5 and 6 built the thing that
answers questions and the store it answers from. This feature is the ruler.

## Why

An agent built on a language model fails quietly. A normal bug throws an error or
returns something obviously broken. An agent bug returns a confident, well-written
answer that is wrong: "you qualify for the Pell Grant" with a quote that the Pell
Grant document does not contain. Nothing crashes. A user just gets told the wrong
thing, and for a tool about money for college that is the worst kind of failure.

The cost of not having this feature is that every later change is a guess. Swap
the model, edit the system prompt, change the chunk size, add a document: any of
them can make answers better or worse, and without a score you find out from a
user. The build plan sets three targets (over 80% right status, over 70% right
citation, under 10% invented content), and a target you cannot measure is a
wish.

It also matters for the project's purpose. This repo is a portfolio piece about
productionizing an AI system, and "we measure quality, and here is the trend"
is most of what separates a demo from a product.

## Key concepts

**Evaluation** is measuring how good a system is on purpose, with a fixed set of
questions, so the numbers mean the same thing every time you run them. It is
different from testing in one way that matters. A unit test says "this function
returns 4 for 2+2", and it either passes or fails. An evaluation of a model says
"of 75 attempts, 82% had the right status", and it is a rate, because the thing
being measured is not deterministic. Think of a driving test versus a smoke
detector check. A smoke detector is pass or fail. A driving test is a score.

**A labeled dataset (a "golden set")** is the fixed list of questions together
with the answers a human decided are correct. Here each entry is a *profile*: a
short description of a student, plus the expected status (`eligible`, `partial`,
or `not_eligible`) and the rule that should be quoted. The answer key is the
whole point, and it is only as trustworthy as the person who wrote it. That is
why this feature keeps the labels in a plain JSON file that a person can read
and argue with.

**Eligibility accuracy** is the share of attempts where the agent's status
matched the label. It answers "did it reach the right conclusion?".

**Citation accuracy** is the share of attempts where the agent quoted the right
rule from the right program. This is the metric that is specific to ScholarLens.
The product promise is not "we tell you yes or no", it is "we tell you which
sentence of which rulebook says so". An agent can land on the right status for
the wrong reason (a lucky guess, or quoting a different rule), and status
accuracy alone would call that a success.

**Hallucination** is when a model states something that is not backed by the
material it was given. Here it has a narrow, checkable meaning: the agent quoted
a clause and that clause does not appear anywhere in our documents, or it said
`eligible` or `partial` with no clause at all. The second case is a rule in the
system prompt ("never set eligible or partial without a quoted clause"), so
breaking it counts. Checking whether a quote appears in the corpus is called a
**grounding check**: is the claim grounded in the source?

**Consistency** asks whether the agent gives the same status when you ask the
same question again. Language models sample their output, so two runs can differ.
An agent that says `eligible` twice and `not_eligible` once for the same student
is not something a student can rely on, even if it is right two times out of
three. That is why each profile is run several times.

**Tool-call count and latency** are the cost side. The agent decides whether to
search the knowledge base, search the web, or both. Each call takes time and
money, so "how many calls per question" and "how long per question" are worth
tracking, the same way you would track how many database queries a page makes.

**Deterministic scoring versus an LLM judge.** One popular way to grade model
output is to ask another model "is this answer good?". It is flexible, but it
is also slow, costs money, and can itself be wrong or inconsistent, so you end
up needing to evaluate the evaluator. This feature does not use one. Every score
is plain text matching, so the same input always gives the same score. The trade
is honesty about a limit: a correct answer worded differently from the label can
be marked wrong. More on that below.

**Normalization** means putting two strings in a common form before comparing
them, so that irrelevant differences do not count. The model may quote
`"At or below roughly $54,600"` and the label may say
`"at or below roughly $54,600"`. Lowercasing and stripping punctuation makes them
equal. The project already had a function for this, `slugify`, which turns any
text into lowercase words joined by hyphens, and this feature reuses it rather
than writing a second one.

**A circuit breaker** is a rule that stops doing something after it has failed
enough times in a row, instead of grinding on. The runner uses a small one: three
engine errors in a row means the engine is down, so stop.

**Rate limiting** is a provider capping how many requests you can make per minute.
It matters in this feature because of what happened when we ran it (see below).

**An append-only log (JSONL)** is a file where you only ever add lines at the
end, one JSON object per line. You never edit old lines. It is the simplest
possible "database" for a history of runs, and it has one nice property: a later
run cannot damage an earlier one.

## Architecture

```
python -m app.evaluation
        |
        v
  __main__.py          load settings, load documents, load + validate profiles,
        |              build the agent, run, print the scorecard
        v
  runner.py            for each profile, for each repeat:
        |                 call the agent, time it, catch engine errors
        |              stop early if 3 engine errors in a row
        |              after all attempts: aggregate, append one line to the log
        |
        +--> agent.check_eligibility_measured(request)   (agent.py)
        |         returns (EligibilityResult, tool_call_count)
        |
        +--> scoring.score_attempt(...)                  (scoring.py)
        |         status right? citation right? invented? which failure kinds?
        |
        +--> scoring.aggregate(...)
                  accuracy, citation accuracy, hallucination rate,
                  mean latency, mean tool calls, consistency

  profiles.py          reads data/evaluation/profiles.json and checks every label
                       against the real documents before anything runs

  data/evaluation-runs.jsonl    one line per completed run (git-ignored)
```

The shape mirrors the ingestion package from feature 6: models, a loader, the
logic, a runner, and a `__main__` that returns an exit code. Someone who has read
one can read the other.

The important structural decision is that scoring is a set of pure functions
(`scoring.py`), meaning they take values in and return values out, with no
network, no clock, and no files. That is what let us check them by hand with
made-up answers. Everything that touches the outside world (the agent, the
clock, the file) lives in `runner.py`.

## What we actually built

### The profiles: [`profiles.json`](../backend/data/evaluation/profiles.json)

Twenty-five synthetic students, drafted from the ten program documents in
`backend/data/programs/`. A profile looks like this (shortened):

```json
{
  "profile_id": "tap-single-independent-over-limit",
  "request": {
    "description": "I am a single, independent student with no dependents and my New York State net taxable income is $35,000. ... Am I eligible for the New York Tuition Assistance Program (TAP)?",
    "income": 35000,
    "state": "New York"
  },
  "expected_status": "not_eligible",
  "expected_program": "New York Tuition Assistance Program (TAP)",
  "expected_citation": "cannot exceed $30,000 for a single, independent student",
  "category": "borderline"
}
```

Three things to notice.

- `expected_citation` is a short phrase copied word for word from the document.
  Citation scoring checks that the agent's quote *contains* that phrase, so the
  phrase has to be short and distinctive. If the label were a whole sentence and
  the agent quoted half of it, a correct citation would be marked wrong.
- `category` is `clear`, `borderline`, or `missing_info` (15, 7, and 3 profiles).
  The build plan asks for a "borderline and edge case review", and a tag is the
  cheapest way to make one possible: the scorecard prints the category next to
  every failure.
- Some profiles have no `expected_program` and no `expected_citation`. Those are
  the "we do not have enough information to decide" cases, where the right
  answer is `partial` and the agent should say what is missing. There is no rule
  to quote, so there is nothing to score for citation. The two fields are
  validated together: both set or both null.

Two decisions here came from the session rather than the code.

**The original labeled set was not in this repo.** The build plan says "preserve
the hand-labeled evaluation", but the file was never carried over from the
capstone project, so the profiles here are freshly drafted from the current
documents, and they need a human to check the labels. (The design doc for
feature 6 says the capstone repo has 30 profiles in `eval/golden_profiles.json`.
That was not looked at when these were written, so it is an open option.)

**Each profile names the program it asks about.** The agent returns one verdict
per request, with one status and one source. If a profile just said "I am a
low-income student in New Jersey, what can I get?", the agent could reasonably
answer about any of four programs and there would be no single correct label. So
every question is "Am I eligible for X?". The cost is that this does not test the
agent choosing *which* program to look at. A "which programs do I qualify for"
flow would need a different result shape, and it is not part of this feature.

### Refusing bad labels: [`profiles.py`](../backend/app/evaluation/profiles.py)

A wrong label produces a wrong score, and nobody notices. So the loader
checks every label against the real documents before a single agent call:

```python
citation = slugify(profile.expected_citation)
if not citation or not any(citation in slugify(body) for body in bodies):
    raise EvaluationInputError(
        f"{profile.profile_id}: expected_citation is not in the program's document"
    )
```

If someone edits a program document and a label goes stale, the run refuses to
start and names the profile. Error messages carry only ids and Pydantic's fixed
text, never the profile's description, because the project rule is that student
text does not go into logs. These profiles are invented, but the code path is the
same one a real request would take, so it follows the rule anyway.

### The scoring rules: [`scoring.py`](../backend/app/evaluation/scoring.py)

`score_attempt` turns one agent answer into an `AttemptResult`. The rules:

- **Status right:** the returned status equals the label. An engine error counts
  as wrong.
- **Citation right:** the returned `source.program` equals the label's program
  *and* the quoted clause contains the label's phrase. Both are compared after
  `slugify`.
- **Invented:** the status is `eligible` or `partial` with no clause or source, or
  the quoted clause is not a substring of any document in the corpus.

Two of those rules were adjusted by thinking about what could go wrong.

*An empty needle matches everything.* In Python, `"" in "anything"` is `True`. If
a clause was only punctuation, it would normalize to an empty string and be
"found" in every document. So `_contains` treats an empty needle as no match, and
an empty clause counts as no clause.

*A partial answer that asks for more information is not a hallucination.* The
first version of the rule penalized every `partial` verdict with no clause. Then
we noticed that `EligibilityResult` itself (in `agent/models.py`) documents that
`supporting_clause` is null "only when the verdict rests on missing information
rather than a rule". So an agent that correctly says "I cannot tell without your
income" would have been scored as inventing something, which punishes the exact
behavior the system prompt asks for. The final rule exempts a `partial` verdict
that lists `missing_info`:

```python
rests_on_missing_info = result.status == EligibilityStatus.PARTIAL and bool(result.missing_info)
```

And one deliberate hole: **answers that used web search are not scored for
invention.** The grounding check compares the quote with our documents, and a
quote taken from a web page will never be in them. Marking every web-sourced
answer as a hallucination would punish the agent for using a tool it is allowed
to use. So those attempts get `hallucinated: null` and are left out of that rate.
The catch is that a wrong web-sourced quote is not detected. That is a limit, not
a feature.

The aggregate numbers (`aggregate`) are plain averages with explicit
denominators. Eligibility accuracy divides by all attempts. Citation accuracy
divides only by attempts where the profile expects a citation. Hallucination rate
divides only by attempts that could be checked. The three targets live in this
file as constants: `0.80`, `0.70`, `0.10`.

Consistency is the fraction of profiles where every attempt completed and all
returned the same status. It is `null` when each profile ran once, because one
attempt cannot disagree with itself. Reporting "100% consistent" for a smoke run
would be a lie the numbers tell.

### Counting tool calls: [`agent.py`](../backend/app/agent/agent.py)

The agent already returned a `tool_trace`, a list of labels like
`"searching program rules"` for the frontend to show. But it deliberately removes
repeats, so a run that searched three times shows one label. That makes it
useless for counting. The change was small: a counter on the agent's dependency
object, incremented at the top of each tool, and a second public method:

```python
async def check_eligibility(self, request):
    result, _ = await self.check_eligibility_measured(request)
    return result
```

`check_eligibility` keeps its signature, so the API route and everything else are
untouched. The evaluation calls `check_eligibility_measured` and gets the count
too. This is the only change to existing behavior in the whole feature, and the
diff is 13 lines.

### The runner: [`runner.py`](../backend/app/evaluation/runner.py)

It walks the profiles in file order, `EVALUATION_REPEATS` attempts each (default
3), one at a time. Sequential on purpose: the model provider limits requests per
minute, and running 25 in parallel would just trigger the limit sooner.

Each attempt is timed with `time.monotonic()` (a clock that cannot jump
backwards, unlike wall-clock time). An `EligibilityEngineError` does not crash the
run. It becomes an `engine_error` attempt and the run continues. Then the circuit
breaker:

```python
if consecutive_errors >= _MAX_CONSECUTIVE_ENGINE_ERRORS:
    raise EvaluationError("engine unavailable: repeated engine errors, run aborted")
```

Without it, a missing API key or a stopped ChromaDB would make every one of the
75 attempts fail, each waiting up to 45 seconds. Nothing is written when a run
aborts, so a broken run cannot leave a row of zeros in the trend history.

A finished run is written as one JSON line, once, at the end, to
`data/evaluation-runs.jsonl`. That file is git-ignored like the ingestion status
file, since it is per-machine output. Each line holds the aggregate numbers and
every attempt, including the quoted clause, so a person can read the citations by
hand. That reading is the "qualitative citation review" the build plan asks for,
and it is the part no automatic score replaces.

### The command: [`__main__.py`](../backend/app/evaluation/__main__.py)

It prints a progress line per attempt (profile id and outcome only), then the
scorecard: each metric with its target and `met` or `MISSED`, mean latency, mean
tool calls, consistency, failure categories, and a list of failing attempts with
expected versus returned status. The exit code is 0 whenever a run completes,
even if a target was missed, and 1 when the run could not happen. A missed target
is a result, not a broken command.

### What happened when we ran it

The real check was a live smoke run (one attempt per profile). It did three
things worth knowing:

- Three attempts completed. One of them, `pell-low-income-undergrad`, a profile
  labeled clearly `eligible`, was scored `wrong_status`. That was not
  investigated. It could be a bad label or a real agent mistake, and telling
  which is exactly the job this tool exists for.
- The next three attempts failed with HTTP 429: the Gemini free tier allows only
  a handful of requests per minute per model, and each agent run makes at least
  two model calls (one to call the retrieval tool, one to write the answer).
- The circuit breaker fired after three failures in a row, the command exited 1
  with a one-line message, and no record was written. That is the abort path
  working on real failures, not a mock.

The consequence is that on a free key a full run of 75 attempts cannot finish
without pausing between attempts. The spec said "no retries", so pacing was not
built. An optional delay setting (default off) was proposed as a follow-up.

### How we know it works

- `ruff check .` passes.
- Profile loading: 25 profiles, all three statuses, all three categories; four
  deliberately broken copies (a citation not in the document, a duplicate id, only
  one of program and citation set, an unknown program) each failed with a message
  naming the profile.
- Scoring: made-up answers covering a good match, a paraphrase, an invented
  clause, a missing clause, a web-sourced answer, an engine error, and a wrong
  status. The aggregates were worked out by hand first (0.8, 0.2, 0.4, mean
  latency 1280 ms, consistency 0.5) and the code returned exactly those.
- The runner, with a fake agent that returns canned answers: two runs produce two
  lines and the first is unchanged; an agent that always fails aborts after three
  calls and leaves no file; an unwritable path gives a controlled error.
- The command with a missing profiles file and with `EVALUATION_REPEATS=0` both
  exit 1 with one line.
- **Not verified:** a complete live run, a second appended live run, and a live
  tool-call count. The rate limit stopped the only live attempt.
- There is no test suite. The project has no test runner configured, so these
  checks were scripts, not tests that remain. Feature 19 is where the scoring
  functions get real unit tests, and they are the first thing that should get
  them.

## What's next

- **Fix the pacing gap and get a first real score.** Either a paid key or a
  small delay setting between attempts. Until a full run finishes, none of the
  three targets has been measured. Then check the profile labels by hand, since
  the first result is as much a test of the labels as of the agent.
- **Consider the original 30 profiles.** If `eval/golden_profiles.json` from the
  capstone exists and covers these programs, comparing against it would be a
  stronger baseline than a set the same person built alongside the code.
- **Features 14 and 15, tracing and metrics.** The run record already holds the
  fields the plan lists (latency, tool calls, the three rates). Feature 15
  turns "latest evaluation results" into Prometheus metrics, and the JSONL
  history is what makes a trend line possible.
- **Feature 17, the `/ops` view** reads this file, or a summary endpoint over it,
  to show evaluation runs next to ingestion health.
- **Feature 18, hardening.** There is deliberately no HTTP endpoint for running an
  evaluation, because it spends model quota. If one is ever added it must be
  protected.
- **Feature 19, testing.** Durable unit tests for `scoring.py`, which is pure
  logic with real edge cases (empty clause, web-sourced, a single attempt).
- **Feature 21, polish.** The plan ends with a final evaluation run against the
  deployed version, which is what this command is for.
- **Known limits to keep in mind.** Scoring is text matching, so a correct answer
  in different words can be marked wrong. The grounding check cannot see web
  sources. And the profiles name their program, so choosing the right program is
  untested.
