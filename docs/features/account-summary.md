---
feature: Account summary
paths:
  - force-app/main/default/classes/AccountSummaryController*.cls*
  - force-app/main/default/lwc/accountSummary/**
  - force-app/main/default/permissionsets/Account_Summary_User.permissionset-meta.xml
specs: []
---

# Account summary

## What it does

A card on the Account page shows how many opportunities are open for the account and what they are worth, so a
sales user sees the pipeline without opening the related list.

## How it works

- `AccountSummaryController.getSummary(accountId)` counts the open opportunities and adds up their amounts in one
  aggregate query, in user mode.
- The `accountSummary` Lightning web component calls it through a wire and shows the count and the amount, or the
  error message when the user can't see opportunities.

## Access

The `Account_Summary_User` permission set grants the Apex class. Users also need read access to opportunities and
their amounts.

## Limits and known issues

- Counts only opportunities the user can see, so two users can see different numbers.
- Amounts are added up in the org's corporate currency.

## History

- Initial version, written by hand as the shakedown baseline.
- Baseline check: a comment tidied by hand, to prove the pipeline end to end before any agent runs.
