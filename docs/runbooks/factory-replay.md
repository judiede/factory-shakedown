# Preparing the PoC tickets (PoC "Before we start" and Step 2)

A replayed ticket is a closed ticket the agents redo, starting where the developer started, so their result can be
compared with the human one. Everything the agents see must come from before the human change.

**This PoC uses open backlog tickets**, because the code isn't in Git yet. Follow sections 1, 2 and 5 for them
(choose and screen, copy into the PoC project, start); sections 3 and 4 apply only once replaying is possible.
Backlog tickets build on `main`, and the spec agent reads the integration sandbox through its read-only user.

## 1. Choose and screen the tickets

1. Pick 15 to 20 tickets closed in the last three to six months: a third small, a third medium, a third larger, one
   or two touching sharing or permissions. Note each one's human pull request and how many review rounds it took.
2. Screen them for personal data before choosing (needs the Jira variables and token in your shell):

   ```bash
   export PYTHONPATH=factory JIRA_BASE_URL=... JIRA_USER=... JIRA_API_TOKEN=...
   python -m factory_kit ticket screen --jql 'key in (SALES-401, SALES-412, SALES-415)'
   ```

   Drop or clean any ticket that isn't `clean`. The factory also redacts emails, phone numbers, record IDs and card
   numbers before the model sees a ticket, but that is a safety net, not the screen.
3. Split them: five or six tuning tickets, the rest held out. Record the split where the agents can't see it (not in
   this repository), with the reference solutions.

## 2. Copy the tickets into the PoC Jira project

For each ticket, create a copy in the PoC project with the summary, description and the comments written **before
development started**. Leave out later comments, development links and attachments with customer data. Note the new
key next to the original; the copies' keys are what the factory uses.

## 3. Create the base branches

For each ticket, find the commit just before the human change, then run from a clone of the PoC repository with
your own credentials (the factory App can't push workflow files, which the base branch needs):

```bash
pip install pyyaml
export PYTHONPATH=factory
python -m factory_kit replay --key POC-12 --before 3f2a9c1 --push
```

This creates `poc/POC-12` (that commit plus one commit with the factory files from `main`) and the tag
`replay/POC-12`. Add ADRs that predate the ticket with `--extra docs/adr/0007-x.md`; leave out anything written
after it. If a later fix to the factory files must reach a base branch, change it through a pull request.

## 4. Check each base branch

Run the factory with nothing to do first: open a pull request against `poc/POC-12` that changes one comment in a
class. **Factory: validate** must build a scratch org from it and pass. If the old code doesn't deploy to a scratch
org, fix the scratch org definition or drop the ticket (poc-plan.md pitfalls).

## 5. Start

Add the `factory-ready` label to the tuning tickets in the PoC project. See [factory-operations.md](factory-operations.md).
