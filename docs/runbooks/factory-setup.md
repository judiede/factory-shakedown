# Setting up the factory (PoC Steps 1 and 2)

Everything here is done once by a factory admin. The check at the end is the Step 1 check from
[poc-plan.md](../poc-plan.md): one workflow logs in everywhere and creates a scratch org.

## 1. The PoC repository

1. Create a private repository in the GitHub Team organization.
2. Import the Salesforce codebase **with its history** (`git clone --mirror`, then push), so replayed tickets can
   start from the commit before the human change. If the code isn't in Git (this PoC's case), retrieve it from the
   sandbox as the baseline, as below; the PoC then uses open backlog tickets on `main`.
3. Add this kit on `main`: `.github/`, `factory/`, `factory-policy.yml`, `AGENTS.md`, `CLAUDE.md`, `config/`, `docs/`.
   Merge `.gitignore` with the project's own.
4. Make sure `package.json` has a `test:unit` script (`sfdx-lwc-jest`) and a `package-lock.json`, so CI can run Jest.
5. Settings → General: turn on **Automatically delete head branches**.
6. Settings → Actions → General: workflow permissions **Read repository contents**; don't allow Actions to approve
   pull requests.

### Baseline from the sandbox (code not in Git)

Run these as a person, with your own login, in an empty folder:

```bash
sf org login web --alias baseline-source --instance-url https://test.salesforce.com
sf project generate --name salesforce --manifest
cd salesforce
# A manifest of everything in the org except managed packages and noise you don't own.
sf project generate manifest --from-org baseline-source --output-dir manifest --name package.xml \
  --excluded-metadata StandardValueSet --excluded-metadata Settings
sf project retrieve start --manifest manifest/package.xml --target-org baseline-source
```

Review `package.xml` before retrieving: drop types the team doesn't maintain in source, such as reports and
dashboards. Then add the factory kit next to the retrieved project, commit both as the first commit on `main`, and
check that a scratch org builds from it (the Step 2 check). Expect to adjust `.forceignore` and the scratch org
definition until it does.

## 2. The factory GitHub App

Create an organization GitHub App (not a personal access token):

| Permission | Access | Why |
| --- | --- | --- |
| Contents | Read and write | push agent branches and the `factory-results` branch |
| Pull requests | Read and write | open pull requests, post reviews and comments |
| Issues | Read and write | labels on pull requests |
| Metadata | Read | required |
| Workflows | **No access** | the App must never change workflow files |
| Administration | **No access** | it can't change rulesets |

Install it on the PoC repository only. Note the **client ID**; generate a **private key**.

## 3. Branch rulesets

One ruleset for `main` and one for `poc/**` (Settings → Rules → Rulesets):

- Require a pull request, **1 approval**, **review from Code Owners**, and **approval of the most recent reviewable push**.
- Dismiss stale approvals when new commits are pushed.
- Required status checks: `guard`, `static`, `scratch-org`, `sandbox` (from "Factory: validate"). Skipped jobs count
  as passed, so one set works for both kinds of base branch.
- Block force pushes and deletions. **Bypass list: empty.**

Leave `spec/*`, `feature/*` and `factory-results` unprotected: the App pushes there.

Replace the placeholder teams in [.github/CODEOWNERS](../../.github/CODEOWNERS) with real ones.

## 4. Labels

```bash
gh label create factory-spec      --color 1C5FB0 --description "Spec pull request written by the factory"
gh label create factory-build     --color 0A8571 --description "Build pull request written by the factory"
gh label create needs-human       --color B0365A --description "The factory stopped; a person takes over"
gh label create needs-spec-change --color 9C6500 --description "The spec can't be built as written"
```

## 5. Salesforce

1. **Dev Hub** in production (Setup → Dev Hub). Create a user on the free **Salesforce Limited Access** license for
   the build agent and CI, with a permission set granting create, read, edit and delete on `ScratchOrgInfo` and read,
   edit and delete on `ActiveScratchOrg`. This is the only agent identity in production, and it sees Dev Hub objects only.
2. **Developer sandbox** from production as the integration target.
3. Two API-only users in the sandbox:
   - **Spec agent** (read-only): API Enabled and View Setup and Configuration. Metadata retrieves also need Modify
     Metadata Through Metadata API Functions, which allows deploys too; grant it only if the agent must retrieve,
     knowing it could then change the sandbox.
   - **CI validator**: API Enabled, Modify Metadata Through Metadata API Functions and Author Apex, for check-only
     deploys with tests.
4. **Apps for the JWT logins.** Generate a key pair per app, upload its certificate, pre-authorize the users' profiles or
   permission sets, note each consumer key (client ID), and set a calendar reminder to rotate the keys.
   - **Production, Dev Hub user: a classic Connected App.** Scratch org creation fails through an External Client App
     (`INVALID_INPUT: The callback URL provided is not valid`); Salesforce's DX guide also says to use a connected app for
     Dev Hubs. New orgs block connected app creation: Setup → External Client App Settings → Allow creation of connected
     apps (some orgs need Salesforce Support for this). Callback `http://localhost:1717/OauthRedirect`, Use digital
     signatures, scopes api, web, refresh_token offline_access.
   - **Sandbox, spec and CI users: an External Client App** with the JWT bearer flow.
5. Edit [config/project-scratch-def.json](../../config/project-scratch-def.json) so scratch orgs match production's
   features and settings.

## 6. Jira

1. A dedicated PoC project. The replayed tickets are copied there (see [factory-replay.md](factory-replay.md)).
2. A **service account** with a scoped API token, limited to the PoC project: browse, comment and edit labels.
3. Install the GitHub for Jira app for the PoC project, so pull requests show on the tickets.

## 7. Model provider

Create a separate workspace for the PoC in the Claude Console, with a monthly spend limit, and an API key in it.
For Amazon Bedrock or Google Vertex AI, change the model IDs in `factory-policy.yml`, replace `ANTHROPIC_API_KEY`
with the provider's settings (`CLAUDE_CODE_USE_BEDROCK=1` and AWS credentials through OIDC, or
`CLAUDE_CODE_USE_VERTEX=1` and Google credentials) in the agent steps, and confirm the data retention and region terms.

## 8. GitHub environments, secrets and variables

**Environment `factory-agent`**, deployment branches: `main` only. Agent workflows run on `main`, so no pull request
can reach these secrets.

| Secret | Value |
| --- | --- |
| `ANTHROPIC_API_KEY` | the PoC workspace key |
| `JIRA_API_TOKEN` | the service account's scoped token |
| `FACTORY_APP_PRIVATE_KEY` | the App's private key |
| `SF_DEVHUB_JWT_KEY` | private key for the Dev Hub user's External Client App |
| `SF_SPEC_JWT_KEY` | private key for the spec agent user in the sandbox |

**Environment `integration`**, no branch restriction (pull request CI uses it):

| Secret | Value |
| --- | --- |
| `SF_CI_JWT_KEY` | private key for the CI validator in the sandbox |
| `SF_DEVHUB_JWT_KEY` | the Dev Hub key, for scratch org validation of replay pull requests |

**Repository variables:**

| Variable | Example |
| --- | --- |
| `FACTORY_ENABLED` | `true` (the kill switch: anything else stops intake and every agent) |
| `FACTORY_IMAGE` | `ghcr.io/your-org/factory-agent@sha256:...` (from the image workflow) |
| `FACTORY_DEFAULT_BRANCH` | `main` |
| `FACTORY_APP_CLIENT_ID` | the App's client ID |
| `JIRA_BASE_URL` | `https://your-site.atlassian.net` |
| `JIRA_USER` | the service account's email |
| `JIRA_PROJECT` | `POC` |
| `SF_DEVHUB_USERNAME`, `SF_DEVHUB_CLIENT_ID`, `SF_DEVHUB_URL` | the Dev Hub user, its app's consumer key, `https://login.salesforce.com` or the My Domain URL |
| `SF_SPEC_USERNAME`, `SF_SPEC_CLIENT_ID` | the spec agent user and the sandbox app's consumer key |
| `SF_CI_USERNAME`, `SF_CI_CLIENT_ID` | the CI validator and the sandbox app's consumer key |
| `SF_SANDBOX_URL` | `https://test.salesforce.com` or the sandbox's My Domain URL |

## 9. The image

Run **Factory: image** (Actions → Factory: image → Run workflow). Its summary shows the image reference with its
digest; put that in `FACTORY_IMAGE`. Rebuilds happen weekly; switch `FACTORY_IMAGE` to a new digest on purpose.
Tool versions are the `ARG` lines in [factory/image/Dockerfile](../../factory/image/Dockerfile); Dependabot proposes
updates to the base image and the actions, and the `ARG` versions are updated by hand.

## 10. Secret scanning

Turn on secret scanning and push protection. Private repositories on GitHub Team need the paid Secret Protection
add-on. CI also runs gitleaks on every pull request, so the factory is covered either way.

## Check (Step 1)

Run **Factory: smoke test**. It logs in to Jira, asks the model for "OK", creates and deletes a scratch org through
the Dev Hub, and logs in to the sandbox as the spec agent and as the CI validator. Every line must pass.

## Check (Step 2)

1. Open a pull request by hand that changes one Apex class. **Factory: validate** must go green: guard, static, and
   sandbox (or scratch-org for a `poc/*` base).
2. Note how long scratch org creation, deploy and the test run take; set `time_minutes` in `factory-policy.yml` from them.
