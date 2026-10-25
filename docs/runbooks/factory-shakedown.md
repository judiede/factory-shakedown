# Shakedown: the factory end to end with test accounts

Goal: prove the plumbing before the real PoC. One or two small tickets go from Jira through spec, Gate 1, build, CI,
review and Gate 2, using a Salesforce Developer Edition org, a test Jira site, an Anthropic API key and a **public**
GitHub repository on GitHub Free. Nothing here produces PoC results; it shows that every connection works.

Ready on your PC:

- `C:\Users\diede\factory-shakedown`: the shakedown repository, committed on `main`: the factory kit plus a tiny
  sample feature (account summary: an Apex controller, a Lightning web component, a permission set).
- `C:\Users\diede\factory-shakedown-keys`: `factory-jwt.key` (private, readable only by you) and `factory-jwt.crt`
  (the certificate Salesforce gets). Never commit or share the key.
- The test tickets: in `docs/runbooks/factory-shakedown-tickets.md` of the Faber repository (kept out of this repository, which the agents read).

## How the shakedown differs from the real PoC

| Real PoC | Shakedown | Why |
| --- | --- | --- |
| Private repo on GitHub Team | Public repo on GitHub Free | Free plans have environments and rulesets only on public repos |
| Integration sandbox | The Developer Edition org itself | Developer Edition orgs can't create sandboxes |
| Separate least-privilege users | Your admin user for all three roles | The Limited Access license exists only in Enterprise and above |
| Separate keys per user | One key pair | One user |
| No bypass on rulesets | Admin bypass for pull requests only | You are the only person: you can't approve your own pull requests |

**Public means public.** Workflow logs, run logs on `factory-results` and the transcripts in artifacts can be read by
anyone. Use only the sample code and the test tickets. Lower the retention in Settings → Actions → General →
Artifact and log retention, for example to 7 days.

**Scratch org limits.** A Developer Edition Dev Hub allows 3 active scratch orgs and 6 new ones a day. The smoke test
uses one; every build run, and every fix attempt, uses one. Plan on about two tickets a day.

## 1. Salesforce Developer Edition (about 15 minutes)

1. Setup → **Dev Hub** → turn on **Enable Dev Hub**.
2. Note your user name (Setup → Users, or your profile). The shakedown uses it for every role.
3. Setup → **External Client App Manager** → **New External Client App**:
   - Name `Factory Shakedown`, your contact email, distribution state **Local**.
   - **Enable OAuth**. Callback URL `http://localhost:1717/OauthRedirect`. Scopes: *Manage user data via APIs (api)*
     and *Perform requests at any time (refresh_token, offline_access)*.
   - Flow enablement: **Enable JWT Bearer Flow**, and upload `factory-jwt.crt`.
   - Create it. On **Policies** → Edit → OAuth policies: permitted users **Admin approved users are pre-authorized**,
     then add the profile **System Administrator**. Save.
   - On **Settings** → OAuth settings → **Consumer Key and Secret**: copy the consumer key. It's the client ID below.
   - Allow a few minutes before the first login.
4. Optional check from your PC (PowerShell):

   ```powershell
   sf org login jwt --username <your user name> --client-id <consumer key> `
     --jwt-key-file C:\Users\diede\factory-shakedown-keys\factory-jwt.key `
     --instance-url https://login.salesforce.com --alias shakedown
   sf org list limits --target-org shakedown | Select-String Scratch
   sf org logout --target-org shakedown --no-prompt
   ```

   Norton's web shield intercepts HTTPS on this PC. If the login fails with a certificate error, first run
   `$env:NODE_EXTRA_CA_CERTS = "C:\Users\diede\factory-shakedown-keys\norton-root.crt"`.

## 2. Jira (about 10 minutes)

1. Create a software project, for example key `FAC`. Labels need no setup; `factory-ready` appears when first used.
2. Create an API token at id.atlassian.com → Security → API tokens. Note it, your account email and the site URL
   (`https://<site>.atlassian.net`).
3. Create the tickets from `factory-shakedown-tickets.md` in the Faber repository. Don’t label them yet.

## 3. Anthropic (about 5 minutes)

In the Claude Console, create a workspace `factory-shakedown` with a spend limit (for example $25) and an API key in it.

## 4. GitHub (about 20 minutes)

1. Create an empty **public** repository `factory-shakedown`, with no README.
2. In `C:\Users\diede\factory-shakedown`, make sure `.github/CODEOWNERS` names your GitHub user, then push:

   ```powershell
   git add .github/CODEOWNERS; git commit -m "Set the code owner"
   git remote add origin https://github.com/<you>/factory-shakedown.git
   git push -u origin main
   ```

3. Settings → Code security: turn on **secret scanning** and **push protection** (free on public repositories).
   Settings → Moderation options → Interaction limits: **limit to collaborators**. Settings → General: turn on
   **Automatically delete head branches**. Settings → Actions → General: workflow
   permissions **Read repository contents and packages**; leave *Allow GitHub Actions to create and approve pull
   requests* off; require approval for fork pull requests from outside collaborators.
4. **GitHub App**: your profile → Settings → Developer settings → GitHub Apps → **New GitHub App**:
   - A unique name such as `factory-shakedown-<you>`, homepage URL = the repository URL, webhook **off**.
   - Repository permissions: **Contents** read and write, **Pull requests** read and write, **Issues** read and write.
     Metadata read is added for you. Give nothing else; especially no **Workflows** permission.
   - Installable only on this account. Create it, note the **Client ID**, **Generate a private key** (a `.pem` file;
     keep it with the other keys), then **Install App** on the `factory-shakedown` repository only.
5. **Labels** (Issues → Labels): `factory-spec`, `factory-build`, `needs-human`, `needs-spec-change`.
6. **Environments** (Settings → Environments):
   - `factory-agent`, deployment branches limited to `main`. Secrets: `ANTHROPIC_API_KEY`, `JIRA_API_TOKEN`,
     `FACTORY_APP_PRIVATE_KEY` (the `.pem` contents), `SF_DEVHUB_JWT_KEY` and `SF_SPEC_JWT_KEY` (both the contents of
     `factory-jwt.key`).
   - `integration`, no branch limit. Secrets: `SF_CI_JWT_KEY` and `SF_DEVHUB_JWT_KEY` (both `factory-jwt.key`).
7. **Repository secrets and variables** (Settings → Secrets and variables → Actions). In a public repository,
   store the values that identify you as **repository secrets**, so they're masked in the public logs: `JIRA_BASE_URL`,
   `JIRA_USER`, the three `SF_*_USERNAME` and the three `SF_*_CLIENT_ID`. The workflows read a secret first and fall back
   to a variable of the same name. The rest are **variables**:

   | Variable | Value |
   | --- | --- |
   | `FACTORY_ENABLED` | `false` for now; `true` after the smoke test |
   | `FACTORY_DEFAULT_BRANCH` | `main` |
   | `FACTORY_APP_CLIENT_ID` | the App's client ID |
   | `FACTORY_IMAGE` | set in step 5.1 |
   | `JIRA_PROJECT` | your project key, such as `KAN` |
   | `SF_DEVHUB_URL`, `SF_SANDBOX_URL` | `https://login.salesforce.com`, both |

8. **Ruleset** (Settings → Rules → Rulesets → New branch ruleset) for the default branch: require a pull request with
   1 approval, review from code owners and approval of the most recent push; block force pushes. Add the required
   status checks `guard`, `static` and `sandbox` after they have run once. Bypass list: **Repository admin, for pull
   requests only**, so you can merge your own changes; agent pull requests still need your approval.

## 5. First runs

1. **Image.** Actions → *Factory: image* → Run workflow. Copy the reference from its summary
   (`ghcr.io/<you>/factory-agent@sha256:…`) into `FACTORY_IMAGE`. If later jobs can't pull it, open the package
   (your profile → Packages → factory-agent) → Package settings → Manage Actions access → add the repository.
2. **Smoke test.** Actions → *Factory: smoke test* → Run workflow. Every line must pass: Jira, the model, a scratch org
   created and deleted through the Dev Hub, and both sandbox logins (here: your dev org).
3. **Green baseline.** On a branch, change a comment in `AccountSummaryController.cls` and add a line to the History
   section of `docs/features/account-summary.md` (the docs check wants both). Open a pull request: *Factory: validate*
   must pass `guard`, `static` and `sandbox`. Merge it with your bypass. Now add the required checks to the ruleset.
4. **First ticket.** Set `FACTORY_ENABLED` to `true`. Add the label `factory-ready` to the first ticket. Within about
   10 minutes *Factory: spec* runs and a spec pull request appears.
   - Spar: comment `/factory why a picklist and not a text field?` and wait for the answer.
   - Approve and merge the spec. *Factory: plan* starts the build; a code pull request follows, CI runs, the
     reviewer agent comments. Approve and merge.
5. **Questions path.** Label the third ticket. The agent should post questions to Jira and keep the spec in draft.
   Answer in a Jira comment, add `factory-ready` again, and check that the spec picks up the answers.

## When something fails

| Symptom | Likely cause |
| --- | --- |
| Smoke test: Dev Hub `user hasn't approved this consumer` | The External Client App isn't active yet, or the System Administrator profile isn't pre-authorized |
| `invalid_grant` / `audience is invalid` | Use `https://login.salesforce.com` as both Salesforce URLs |
| Jira `401` | `JIRA_USER` must be the email of the account that created the token |
| `docker pull` denied | The package doesn't grant the repository access (step 5.1) |
| Nothing happens after labeling | `FACTORY_ENABLED` isn't `true`, or the label isn't exactly `factory-ready` in project `JIRA_PROJECT` |
| A pull request can't be merged | `YOUR-GITHUB-USER` still in CODEOWNERS, or a required check never ran |
| `quota` errors on scratch orgs | The Developer Edition limit: wait for the daily reset, or delete active scratch orgs |

Every run's summary page and artifacts (prompt, permission settings, transcript) show what happened.
