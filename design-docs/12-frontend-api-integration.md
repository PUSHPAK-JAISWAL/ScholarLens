# 12 - Frontend <-> API integration

## What

By the time this feature started, `/check` already called the real FastAPI
`/eligibility` endpoint — features 10 and 11 had pulled that wiring forward
with a hand-written `fetch` call. What feature 12 actually did was replace
that hand-rolled data-fetching code with **TanStack Query**, a library built
specifically for talking to a server, and close a real gap the hand-rolled
version had: it trusted the server's response shape instead of checking it.

Concretely: `EligibilityChecker.tsx` went from a manual `useState` + `fetch` +
try/catch dance to a single `useMutation` call, `lib/eligibility.ts` gained
runtime checks that reject a malformed response instead of rendering
`undefined` all over the page, and the whole app got wrapped in a
`QueryClientProvider` so any future feature (the `/ops` dashboard in feature
17, for instance) can use the same library instead of reinventing this.

## Why

Two different problems, both about what happens when a network call doesn't
go the way you hoped.

**The retry problem.** The `/eligibility` call can fail for reasons that have
nothing to do with whether the student is eligible: the request can time out,
the wifi can drop for a second, the backend agent can be briefly
unavailable. Before this feature, any of those meant one thing: an error
message, and the student has to notice, re-read the form, and click the
button again by hand. That's a bad experience for a failure that had nothing
to do with them and might not even happen twice. But "just retry
automatically" is not free either — this endpoint calls a large language
model, which costs real money and real seconds per call, so retrying
something that failed for a *real* reason (the server looked at the request
and said no) would burn both for no benefit. The fix needed to tell those two
kinds of failure apart, which is exactly what a mutation library is built to
do and a bare `fetch` call is not.

**The trust-boundary problem.** `lib/eligibility.ts` had this line:

```ts
return (await response.json()) as EligibilityResult;
```

`as` is TypeScript's "trust me" operator. It doesn't check anything at
runtime — it just tells the compiler to stop asking questions. As long as the
backend and frontend agree on the shape of `EligibilityResult`, that's
invisible. But an API boundary is exactly the place that agreement can break
without anyone touching this file: someone changes the Pydantic model on the
backend, a proxy in front of the API mangles a response, `NEXT_PUBLIC_API_URL`
points at the wrong host in some environment. When that happens, `as` doesn't
raise an error where the bad data enters — it lets `undefined` quietly travel
downstream until something *else* breaks, usually somewhere much harder to
debug. `blueprint/context/coding-standards.md` already had a rule for this
("validate/parse API responses at the boundary rather than trusting shapes"),
written before this feature existed, and an `/audit` pass had already flagged
this exact line as finding **F-20**, explicitly noting that this feature was
the natural place to fix it.

## Key concepts

**A mutation, in TanStack Query's vocabulary, is a request that changes
something or has a side effect — as opposed to a query, which just reads
data you might want to cache and reuse.** `POST /eligibility` doesn't persist
anything on the backend, but it does spend money and time and produce a
one-off result tied to whatever the student just typed, so it fits the
"mutation" shape (fire it on demand, track its in-flight/success/error state)
much better than the "query" shape (fetch on mount, cache by key, refetch in
the background). `useMutation` is the hook for the first kind.

**A discriminated union is a type made of several variants that share one
field you can check to find out which variant you actually have.** The old
code built one by hand:

```ts
type CheckState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; result: EligibilityResult }
  | { status: "error"; message: string; fields?: string[] };
```

Checking `state.status === "success"` let TypeScript know `state.result`
must exist in that branch — that's what "discriminated" means, the `status`
field discriminates between the variants. `useMutation`'s return value is
the same idea, built in: `mutation.isSuccess`, `mutation.isPending`, and
`mutation.isError` are the discriminant, and once you check one of them,
`mutation.data` or `mutation.error` is known to exist without a manual cast.
That's why replacing the hand-built union with the library's own state didn't
need any extra type gymnastics — the code just moved from a `switch`-like
check on a custom field to the same check on a field the library already
tracks for you.

**Retry and retry delay are two separate decisions.** *Retry* answers "should
this failure try again at all?" *Retry delay* answers "how long to wait
before the next attempt?" TanStack Query lets you supply a function for
each, and it calls both with a **failure count** — but the count it passes is
the number of failures *so far*, starting at `0` for the very first failure,
not `1`. That distinction mattered here (see the bug story below).

**Exponential backoff** means each retry waits longer than the last —
typically doubling — instead of retrying instantly or waiting a fixed amount
every time. The reasoning: if a request just failed because a server or
network hiccuped for a moment, retrying almost immediately is often fine, but
if it's still failing after that, waiting longer before trying again gives
whatever's wrong more room to recover, and avoids hammering an already
struggling backend.

**A type guard is a function whose job is to answer "is this value actually
the shape I think it is?" at runtime, in a way TypeScript's type checker can
use.** A normal function returns `boolean`; a type guard returns
`value is SomeType`, and once you check it, TypeScript narrows the variable
to that type inside the `if`. This is TypeScript's answer to the "boundary"
problem above: instead of asserting a shape with `as` and hoping, you check
it with a function like `isEligibilityResult`, and only *proven* correct data
gets treated as `EligibilityResult` from that point on. This is sometimes
summarized as "parse, don't validate" — the check and the type-narrowing
happen in the same place, so there's no gap where you could forget one but
keep the other.

## Architecture

```
EligibilityForm (unchanged)
       |  onSubmit(request)
       v
EligibilityChecker.tsx
       |
       |  mutation.reset(); mutation.mutate(request)
       v
useMutation({ mutationFn: checkEligibility, retry, retryDelay })
       |                                   ^
       |  calls                           needs a QueryClient from context
       v                                   |
lib/eligibility.ts                  app/providers.tsx  (mounted in layout.tsx)
  checkEligibility()                  <QueryClientProvider client={...}>
       |  fetch() -> parse -> validate
       v
  isEligibilityResult() / isErrorDetail()   <-- type guards, the boundary check
       |
       v
  throws EligibilityClientError{ kind: "network" | "timeout" | "api" }
       |
       v
mutation.isError / mutation.error  ->  describeError()  ->  message shown to user
```

The important line in that diagram is the one carrying `kind`. Everything
downstream — whether to retry, what message to show, whether to highlight a
form field — branches on that one property, which is what makes the retry
logic and the error-message logic each a few lines instead of a maze of
special cases.

## What we actually built

### The provider: [`app/providers.tsx`](../frontend/src/app/providers.tsx)

```tsx
"use client";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
```

The `useState(() => new QueryClient())` (rather than just
`const queryClient = new QueryClient()`, or creating it at module scope) is
the standard Next.js App Router pattern for this library, and it's worth
understanding *why* it's written this way rather than copying it blindly.
Next.js can render a component on the server to produce the initial HTML.
If the `QueryClient` lived at module scope, every request the server handles
would share the *same* client and its cache — one student's in-flight
request could theoretically bleed into another's response. Creating it
inside `useState` means each component instance (in practice, each page
load) gets its own client, and `useState`'s lazy-initializer form
(`useState(() => ...)`, not `useState(new QueryClient())`) means the
`QueryClient` constructor only runs once per component instance instead of
on every re-render. This app doesn't do anything with the server-rendering
side of this yet, but wiring it correctly now means feature 17's `/ops`
dashboard (which will have several real queries, unlike this feature's
single mutation) doesn't inherit a subtle bug later.

### The boundary check: [`lib/eligibility.ts`](../frontend/src/lib/eligibility.ts)

```ts
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isEligibilityResult(value: unknown): value is EligibilityResult {
  if (!isRecord(value)) return false;
  return (
    STATUSES.includes(value.status as EligibilityStatus) &&
    typeof value.explanation === "string" &&
    (value.supporting_clause === null || typeof value.supporting_clause === "string") &&
    (value.source === null || isSource(value.source)) &&
    isStringArray(value.missing_info) &&
    isStringArray(value.tool_trace)
  );
}
```

Every field in `EligibilityResult` gets its own check, mirroring the
Pydantic model on the backend (`backend/app/agent/models.py`) field for
field. If a check fails, `checkEligibility` throws the same
`EligibilityClientError` type the network and timeout paths already used,
tagged `kind: "api"` with a generic "unexpected response" message — so a
malformed response degrades into the same error UI as any other server
problem, rather than crashing the page or rendering blanks.

The error-envelope path (`{ error: { code, message, fields } }`) got the same
treatment, which closes finding **F-20** completely rather than half of it —
the original finding named both the success shape and the error shape as
unchecked casts.

### The retry rule and the bug it hid: [`EligibilityChecker.tsx`](../frontend/src/components/check/EligibilityChecker.tsx)

```ts
retry: (failureCount, error) =>
  failureCount < MAX_TRANSPORT_RETRIES && isRetryableTransportError(error),
retryDelay: (failureCount) => (failureCount + 1) * 1000,
```

`isRetryableTransportError` only returns true for `kind: "network"` or
`kind: "timeout"` — the two cases where the request never got a real answer
from the server at all. A `503` (the backend's own "engine unavailable"
response) or a `422` (validation) is a real answer, just not the one anyone
wanted, so those never retry automatically; the student can already resubmit
by hand any time, since the form stays enabled.

The `retryDelay` line looked right and wasn't. The first version was
`(failureCount) => failureCount * 1000`, on the reasoning "delay should be
1000ms times the number of failures so far." That's true in plain language
and wrong against this specific library, because — as noted above —
TanStack Query calls `retryDelay` with the failure count *before* it's
incremented for the attempt about to happen: `0` after the first failure,
then `1` after the second. `failureCount * 1000` therefore produced `0`ms
then `1000`ms — an instant retry followed by a one-second one — not the
intended 1s-then-2s backoff. This survived `tsc --noEmit`, `eslint`, and a
first read of the diff, because it's not a type error or a style issue, it's
a semantic mismatch with a specific library's calling convention that only
shows up if you read that library's source or its behavior directly. It was
caught by running `/code-review`'s Spec-axis sub-agent, which had been told
to check the diff's retry behavior against the spec's stated "1s/2s backoff"
line and went and read `node_modules/@tanstack/query-core/src/retryer.ts` to
verify it, rather than trusting the surrounding comment. The fix was a
one-character-shaped change with a comment explaining why it's needed:
`(failureCount) => (failureCount + 1) * 1000`.

The same review pass flagged a smaller, non-functional issue: `isSource`,
`isErrorDetail`, and `isEligibilityResult` each repeated the same
`typeof value !== "object" || value === null` guard. That got pulled into
the shared `isRecord` helper shown above — a Duplicated Code smell, not a
bug, but worth fixing while the file was already open.

### How we know it works

- `npx tsc --noEmit` and `npm run lint` — pass, checked after every step and
  again after both review fixes.
- `npm run build` — fails in this sandbox on a pre-existing, unrelated cause:
  Turbopack can't resolve its own Google Fonts font-loader module for the
  `DM_Sans` import in `layout.tsx`, and this fails identically on `main` with
  none of this feature's changes applied (confirmed with `git stash`).
  Network access itself is fine (`curl` to `fonts.googleapis.com` succeeds).
  Proceeding on typecheck + lint evidence was an explicit call made in the
  completion session, and the same gap already existed before this feature
  (see feature 11's design doc, which hit and documented the same failure).
- `/code-review`'s two parallel axes (Standards, Spec) both ran against the
  diff. Standards found the duplicated-guard smell above. Spec found the
  retry-delay bug above. Both were fixed before merging.
- **Not verified in this session:** an actual browser walkthrough (idle to
  loading to success/error, watching the retry timing happen) — that needed
  a running backend and browser, which this session's implement step
  deliberately doesn't start on its own. It *was* verified afterward, live,
  by the project owner running both servers directly — which is also how a
  second, unrelated bug got caught (see below).

## What's next

- **Feature 13, structured logging + correlation IDs**, and **feature 14,
  OpenTelemetry** are next in the build plan. Neither depends on anything
  from this feature.
- **Feature 17, the `/ops` dashboard**, is the next place this session's
  `QueryClientProvider` setup actually gets exercised by more than one
  mutation — real queries, possibly some caching, maybe a shared query-key
  convention. This feature deliberately built none of that ahead of time.
- **A real bug fell out of finally seeing this page render for real.**
  Testing this feature live (starting both servers by hand) surfaced a
  second, unrelated bug: `globals.css`'s border-radius scale multiplied a
  `999px` base meant only for pill-shaped buttons to build the whole
  `rounded-md`...`rounded-4xl` scale, so any card taller than a button —
  `VerdictCard`, `AgentActivitySteps`, and the landing page's feature cards
  from feature 9 — rendered as a near-ellipse instead of a subtly rounded
  card. That bug predates this feature (it goes back to feature 8's theme
  setup) and was fixed separately, outside the build-plan workflow, as
  `fix/theme-radius-scale` (PR #16). It's worth remembering as a project
  lesson rather than a footnote: this is the first time in the whole
  frontend build (features 8 through 12) that anyone actually loaded a page
  with real data in a real browser, and it immediately found something four
  features' worth of `tsc`/`eslint`/code-review passes had not. Automated
  checks prove the code is well-typed and internally consistent; only a
  render proves it looks right.
