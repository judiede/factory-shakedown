# KAN-1: Customer tier picklist on Account

## Problem

Sales managers want to record a customer tier on each account so the team can prioritise follow-ups. The ticket's
acceptance criteria:

- "Accounts have a picklist field _Customer Tier_ with the values Gold, Silver and Bronze, in that order, and no
  default value."
- "The field has a description and help text that say what each tier means: Gold for strategic accounts, Silver for
  growing accounts, Bronze for everyone else."
- "Users with the _Account Summary User_ permission set can read and edit the field. No profile changes."

Out of scope: page layouts and reports.

## Options compared

| Option | Fit with standard features | Data volume and limits | Security and sharing | Licensing | Maintenance |
| --- | --- | --- | --- | --- | --- |
| A. Standard feature: reuse the standard `Account.Rating` picklist and relabel its values to Gold, Silver and Bronze | Poor fit: Rating already means Hot, Warm or Cold, and changing its values affects every existing record, list view, report and integration that uses it. Its label and help text are standard, so it can't carry the required description | No new storage; existing values would need a data migration | Field access to standard fields is set on profiles or permission sets, so no difference | Included | Risky: repurposing a standard field confuses its meaning and breaks anything that relies on Hot, Warm or Cold |
| B. Declarative: new custom restricted picklist `Account.Customer_Tier__c` with field access granted by the `Account_Summary_User` permission set | Uses standard custom-field metadata only; meets every criterion, including description and help text | One picklist on Account, no automation, no limits involved | Field-level security through the existing permission set, no profile changes; record access stays on the existing Account sharing model | Included in every edition with custom fields | Low: an admin can maintain the values in Setup |
| C. Custom code: an LWC and Apex that store the tier somewhere else, such as a child object or Custom Metadata | No reason to use code for a single attribute; it duplicates what a picklist does | Adds queries and a second object for no benefit | Needs user-mode Apex, its own sharing and more permission set entries | Included | High: code, tests and a component to maintain for a single field |

## Chosen approach

Option B: a new restricted picklist `Customer_Tier__c` on Account with the values Gold, Silver and Bronze in that
order (no alphabetical sorting, no default). Its description and inline help text explain each tier. Read and edit
access goes on the existing `Account_Summary_User` permission set. Decision rules section 1 put declarative
configuration ahead of code, and section 5 says to reuse standard fields first. The standard field option lost
because `Account.Rating` already has a different, widely used meaning (Hot, Warm, Cold), and repurposing it would
change existing data and behaviour. No Flow, Apex or LWC is needed. The decision sets no precedent, so there is no ADR.

Field details for the build agent:

- Label `Customer Tier`, API name `Customer_Tier__c`, type Picklist, restricted (`restricted` = true), `sorted` = false,
  no value marked `default`, not required, not tracked.
- Values (API name = label), in this order: `Gold`, `Silver`, `Bronze`.
- Description: "Customer tier used to prioritise follow-ups. Gold: strategic accounts. Silver: growing accounts.
  Bronze: all other accounts."
- Inline help text: "Gold for strategic accounts, Silver for growing accounts, Bronze for everyone else."
- Permission set `Account_Summary_User`: add a `fieldPermissions` entry for `Account.Customer_Tier__c` with
  `readable` = true and `editable` = true. Keep the existing class access and change nothing else. Add no object
  permissions: Account record access still comes from the user's profile and sharing.

## Impacted metadata

| Type | API name | Status | Change |
| --- | --- | --- | --- |
| CustomObject | Account | existing | Standard object that holds the new field; not changed |
| CustomField | Account.Customer_Tier__c | new | Restricted picklist Gold, Silver, Bronze; no default; description and help text |
| PermissionSet | Account_Summary_User | existing | Add read and edit field permission on Account.Customer_Tier__c |

## Task breakdown

| ID | Task | Depends on | Allowed paths | Work type |
| --- | --- | --- | --- | --- |
| a | Customer Tier field on Account and field access in Account Summary User permission set | – | force-app/main/default/objects/Account/fields/Customer_Tier__c.field-meta.xml, force-app/main/default/permissionsets/Account_Summary_User.permissionset-meta.xml | small |

## Acceptance criteria

1. Given the deployed source, when Account is described, then the field `Customer_Tier__c` exists with the label
   "Customer Tier" and type Picklist.
2. Given the field, when its picklist values are read, then they are exactly Gold, Silver and Bronze, in that order,
   all active, none marked as default, and the picklist is restricted.
3. Given the field, when its metadata is read, then its description and inline help text are not blank, and each
   one names Gold as strategic accounts, Silver as growing accounts and Bronze as all other accounts.
4. Given a user whose only extra permission set is `Account_Summary_User` and whose profile can edit Accounts, when
   they create or update an Account with `Customer_Tier__c` = `Gold`, then the value saves and can be read back.
5. Given a user with the same profile but without `Account_Summary_User` (and no other grant of the field), when field
   access is checked, then `Customer_Tier__c` is neither readable nor editable for them.
6. Given an Account saved without a tier, when it is read, then `Customer_Tier__c` is blank (no default applied).
7. Given the change, when the pull request diff is checked, then no profile and no page layout or report metadata
   is changed.

## Test plan

- Apex: none is needed, because the change contains no Apex. The build agent may check criteria 1, 2 and 6 with a
  deploy plus `sf sobject describe --sobject Account`. It may also check criteria 4 and 5 in the scratch org by
  checking `FieldPermissions` for the permission set
  (`SELECT Field, PermissionsRead, PermissionsEdit FROM FieldPermissions WHERE Parent.Name = 'Account_Summary_User' AND Field = 'Account.Customer_Tier__c'`).
  No test class is added just for coverage.
- Jest: none, because no components change.
- Manual check in the scratch org: assign `Account_Summary_User` to a standard sales user. Open an Account, use the
  Customer Tier field (reachable through inline edit in a list view or the record's field list, because layouts are
  out of scope), and check that the values show in the order Gold, Silver, Bronze, with nothing preselected, and that
  the help text shows. Then remove the permission set and check that the field is no longer visible.

## Security

- Data touched and how sensitive it is: one new business classification on Account. It is not personal data and
  not confidential; no existing data changes.
- Sharing and record access (`with sharing`, `inherited sharing`, user-mode queries): no change. There is no Apex,
  and record access to Accounts still follows the existing org-wide defaults, role hierarchy and sharing rules.
- Object and field access, and the permission set that grants it: field-level read and edit on
  `Account.Customer_Tier__c` granted only through the existing `Account_Summary_User` permission set. Least access
  is met because the ticket asks for edit. The permission set gets no new object permissions, View All or Modify
  All, and no profile changes. Changing a permission set needs a code owner's review (CODEOWNERS).
- Integrations or external calls: none.

## Open questions

None.
