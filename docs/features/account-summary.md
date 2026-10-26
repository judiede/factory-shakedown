---
feature: Account summary
paths:
  - force-app/main/default/classes/AccountSummaryController*.cls*
  - force-app/main/default/lwc/accountSummary/**
  - force-app/main/default/permissionsets/Account_Summary_User.permissionset-meta.xml
  - force-app/main/default/objects/Account/fields/Customer_Tier__c.field-meta.xml
specs:
  - docs/specs/KAN-1.md
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

The same permission set grants read and edit on the `Account.Customer_Tier__c` field (see below). It adds no object
permissions; Account record access still comes from the profile and sharing.

## Customer Tier field

`Account.Customer_Tier__c` is a restricted picklist with the values Gold (strategic accounts), Silver (growing
accounts) and Bronze (everyone else), in that order, with no default value. It has a description and inline help
text that explain each tier. It is not on any page layout or report; admins can add it where needed.

## Limits and known issues

- Counts only opportunities the user can see, so two users can see different numbers.
- Amounts are added up in the org's corporate currency.

## History

- Initial version, written by hand as the shakedown baseline.
- Baseline check: a comment tidied by hand, to prove the pipeline end to end before any agent runs.
- KAN-1: added the Customer Tier picklist on Account and field access in the permission set.
- KAN-1 review: the permission set description now mentions the Customer Tier field access.
