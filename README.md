# Factory shakedown

A public test repository for the agentic engineering factory. It proves the plumbing end to end with a Developer
Edition org, a test Jira project and two or three small tickets, before the real PoC.

**Test data only.** This repository, its workflow logs and its artifacts are public. Never put real code, real
tickets or customer data here.

## What's here

- `force-app/`: a tiny sample feature, an account summary: `AccountSummaryController` (Apex), the
  `accountSummary` Lightning web component and the `Account_Summary_User` permission set.
- The factory kit: `.github/workflows/`, `factory/`, `factory-policy.yml`, `AGENTS.md`.
- Standards, templates and runbooks in `docs/`. Start with `docs/runbooks/factory-shakedown.md`.

## Commands

```bash
npm install            # Jest and Prettier for the sample project
npm run test:unit      # LWC tests
python -m unittest discover -s factory/tests   # the factory kit's tests (needs PyYAML)
```
