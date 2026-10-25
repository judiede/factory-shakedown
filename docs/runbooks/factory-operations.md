# Operating the factory (PoC Steps 4 to 6)

## Start a ticket

Add the label `factory-ready` to the ticket in the PoC Jira project. Within ten minutes the intake run swaps it for
`factory-active` and starts the spec agent.

## Refinement and Gate 1: where to spar with the spec agent

Business questions belong in Jira; solution questions belong in the spec pull request. Every round is a workflow run,
so expect 10 to 30 minutes per answer.

| When | Where | Who | How |
| --- | --- | --- | --- |
| Before the label | Jira | Product owner, tech lead | Refine as usual: problem, acceptance criteria, constraints. Add `factory-ready` only when the ticket is ready. |
| The agent asks | Jira | Whoever owns the answer | Numbered questions arrive as a ticket comment and the ticket gets `factory-needs-clarification`. Answer in a comment, then add `factory-ready` again; the agent updates the spec. |
| You ask | Spec pull request | Tech lead, reviewers | Comment `/factory <question>`, in the conversation or on a line of the spec. The agent answers in the conversation with evidence and doesn't change the spec. When it needs a decision from you, it ends with questions of its own; answer with another `/factory` comment. |
| You decide | Spec pull request | Tech lead | **Request changes** in a review, or comment `/factory revise <what to do>`. The agent revises with the review comments and the whole `/factory` conversation, and replies with one line per point. |
| You approve | Spec pull request | Tech lead | Merge. The plan run starts every task without dependencies and comments the plan on the ticket. |

Details:

- The spec agent opens the pull request `<KEY>: spec – <title>` with `docs/specs/<KEY>.md`, labeled `factory-spec`.
  With open questions it stays in draft.
- `/factory` must start the comment, and only people with write access to the repository can use it. The factory
  reacts with 👀 when it picks a comment up. Several questions asked while a reply is being written are answered together.
- A plain comment, or a review submitted as **Comment**, doesn't reach the agent; use `/factory` or **Request changes**.
- Limits from `factory-policy.yml`: `discuss.turns` replies per pull request and `discuss.cost_usd` per reply;
  `spec.revision_rounds` revisions, then the pull request gets `needs-human`. Replies are logged on `factory-results`
  with mode `discuss` and don't count as revision rounds, so the Gate 1 measure stays comparable.
- On replayed tickets the agent answers from the repository only; building a scratch org for a question isn't worth it.

The guard check on a spec pull request lints the spec, checks every `existing` name against the base branch, and
fails on any change outside `docs/specs/<KEY>.md` and `docs/adr/`.

## Gate 2: the code

Each task becomes a pull request `<KEY>: <task>`, labeled `factory-build`, from `feature/<KEY>-<task>-<slug>`.

1. **Factory: validate** runs. If it fails, the build agent gets the failed logs and pushes a fix, up to
   `fix_attempts` times within the task's cost cap. Then the pull request gets `needs-human`.
2. When it passes, the reviewer agent comments (it can't approve).
3. A code owner reviews. **Request changes** to send it back to the agent, or **approve and merge**. Merging starts
   the tasks that depended on this one. When all tasks are merged, the ticket gets `factory-merged`.

## When the factory stops

| Signal | Meaning | What to do |
| --- | --- | --- |
| `needs-human` on a pull request | budget used up, scope violation, or the agent made no usable change | take over the branch, or close the pull request with a reason category |
| `needs-spec-change` (draft PR) | the build agent says the spec can't be built as written; the reason is in the PR | amend the spec through a spec pull request (add `factory-ready` to the ticket), then close this one |
| `factory-needs-human` on the ticket | any factory run for the ticket failed or stopped | open the linked run |
| Guard fails on a build PR | the agent changed files outside its task, or a feature doc is missing | close it, or fix by hand |

Rejecting a pull request: close it with a comment starting with the reason category: `wrong-spec`, `wrong-code`,
`missing-context`, `pipeline`, `ambiguous-ticket`. Step 6 counts these.

## Kill switch

Set the repository variable `FACTORY_ENABLED` to `false`. Intake, the router and every agent workflow check it
before starting; runs in progress finish their current step. CI keeps validating pull requests.

## Budgets

`factory-policy.yml` holds them, per task work type (small, medium, large) and for specs and reviews. Agent commits
carry `Factory-Cost-USD` and `Factory-Mode` trailers; the build job adds them up before every fix or revision and
stops when a cap is reached. The plan run stops starting tasks once a ticket has spent `ticket_cost_usd`.

## Logs and results (Step 6)

- **Run log**: one JSON record per agent run on the `factory-results` branch, under `runs/<yyyy-mm>/`, in the shape of
  [factory/schemas/run-log.schema.json](../../factory/schemas/run-log.schema.json): ticket, task, role, outcome,
  model, prompt version, turns, tokens, cost, durations.
- **Transcripts**: every agent run keeps its prompt, permission settings, full transcript (every tool call) and
  outputs as a workflow artifact for 90 days. Download the ones you need for evidence before they expire.
- **Screenshots** of LWCs are on `factory-results` under `screenshots/` and shown in the pull requests.

## Changing the factory

Prompts, policy, workflows and the image change through pull requests to `main`, reviewed by the factory admins.
Each run records the prompt file and its hash, so results can be traced to the version that produced them. Freeze
prompts and policy before running the held-out tickets.

## Running the tests

```bash
pip install pyyaml
python -m unittest discover -s factory/tests
```
