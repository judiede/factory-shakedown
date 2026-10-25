# Security rules

Rules every change follows. CI enforces some of them (Code Analyzer, scope and docs checks); reviewers and the
reviewer agent check the rest. A spec's security section explains how the change meets them.

## Data access in Apex

- Every class declares its sharing: `with sharing` by default, `inherited sharing` for utilities, and
  `without sharing` only with a comment and an ADR explaining why.
- Database operations run in user mode: `[SELECT ... WITH USER_MODE]`, `Database.query(q, AccessLevel.USER_MODE)`,
  `Database.insert(records, AccessLevel.USER_MODE)`. System mode needs a comment explaining why.
- Dynamic SOQL uses bind variables, never string concatenation of user input.
- No SOQL or DML inside loops.

## Access is granted with permission sets

- New objects, fields, classes, tabs and custom permissions are granted through permission sets or permission set
  groups, never profiles. Agents may not change profiles at all.
- A permission set grants the least access the job needs: read before edit, no View All or Modify All without an ADR.
- Changes to sharing rules, permission sets, profiles and integrations always get a human review (CODEOWNERS).

## Secrets, IDs and data

- No hard-coded record IDs, user IDs, org IDs, URLs of an org, or credentials. Use Custom Metadata, Named
  Credentials and External Credentials.
- No customer data or personal data in code, tests, docs, screenshots or commit messages. Tests create their own data.
- Integrations use Named Credentials; no endpoints or tokens in Apex.

## Lightning web components

- No `innerHTML` or `lwc:dom="manual"` with data from users or records.
- Apex methods called from components check access through user-mode queries.
- Anything exposed to guest or Experience Cloud users needs an ADR and a security review.

## Tests

- Apex tests run as a user with only the intended permission set (`System.runAs`), and as one without it.
- Tests assert behaviour, not just coverage. Aim for 85% coverage on new classes.
