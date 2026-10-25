# KEY-123: Short title of the change

<!-- Spec template. The spec agent copies this file to docs/specs/<KEY>.md. CI parses the two tables
     (Impacted metadata, Task breakdown) and the Open questions section, so keep their shape. -->

## Problem

What the user needs and why, in two to five sentences. Quote the ticket's acceptance criteria where they exist.

## Options compared

Always include the standard-feature option, even when it loses.

| Option | Fit with standard features | Data volume and limits | Security and sharing | Licensing | Maintenance |
| --- | --- | --- | --- | --- | --- |
| A. Standard feature | | | | | |
| B. Declarative (Flow, validation rule) | | | | | |
| C. Custom code (Apex, LWC) | | | | | |

## Chosen approach

Which option, why, and the criterion that decided it. Link the ADR when the decision sets a precedent.

## Impacted metadata

Every component the change creates or relies on. Status is `existing` (it must already exist on the base branch,
or in the org for standard and managed components) or `new`. Child components use `Object.Child`.

| Type | API name | Status | Change |
| --- | --- | --- | --- |
| CustomObject | Account | existing | Lookup target |
| CustomObject | Example__c | new | Holds one row per example |
| CustomField | Example__c.Amount__c | new | Currency, required |

## Task breakdown

One pull request per task. `Depends on` lists task IDs that must merge first. `Allowed paths` are repo-relative
globs, comma-separated: the build agent can change nothing else, apart from feature docs in `docs/features/`.
Work type sets the budget: small, medium or large.

| ID | Task | Depends on | Allowed paths | Work type |
| --- | --- | --- | --- | --- |
| a | Object, fields and permission set | – | force-app/main/default/objects/Example__c/**, force-app/main/default/permissionsets/Example_User.permissionset-meta.xml | small |
| b | Apex service with tests | a | force-app/main/default/classes/ExampleService*.cls* | medium |

## Acceptance criteria

1. Given …, when …, then ….

## Test plan

- Apex: which classes and scenarios, including bulk (200 records) and a user without the permission set.
- Jest: which components and behaviours.
- Manual check in the scratch org: what a reviewer should click.

## Security

- Data touched and how sensitive it is:
- Sharing and record access (`with sharing`, `inherited sharing`, user-mode queries):
- Object and field access, and the permission set that grants it:
- Integrations or external calls:

## Open questions

None.
