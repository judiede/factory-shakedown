# Decision rules

How to choose between Salesforce's standard features, declarative tools and code. The spec agent applies these
when it compares options, and reviewers hold specs to them at Gate 1.

> Starting point: adapt the sections marked **Team decision** to how this org is actually built before
> Step 4 of the PoC, and record each change as an ADR.

## 1. Prefer, in this order

1. **A standard feature** that meets the need, even if it needs some configuration or a small process change.
   Check the current release notes: Salesforce ships three releases a year.
2. **Declarative configuration**: fields, validation rules, record-triggered Flows, screen Flows, Dynamic Forms,
   Lightning App Builder.
3. **Code**: Apex and Lightning web components, when declarative tools can't meet the need or would be harder
   to maintain than the code.

## 2. Flow or Apex

Use a record-triggered Flow when all of these hold:

- the logic fits on one screen of Flow Builder and an admin could maintain it;
- it doesn't need complex collections, maps, recursion or callouts with error handling;
- it doesn't process large data volumes in one transaction.

Use Apex when any of these hold:

- the logic is complex, reused in several places, or needs unit tests with many cases;
- it handles bulk data, callouts with retries, or precise transaction control;
- an object already has Apex trigger logic for the same event (don't mix Flow and Apex on one object and event
  without an ADR saying how they are ordered).

## 3. Triggers (Team decision)

- One trigger per object, with no logic in it; it delegates to a handler class.
- Handler framework: **name the framework used in this org**, and follow its pattern for new handlers.
- Every handler is bulk-safe and can be switched off by a Custom Metadata or Custom Setting flag.

## 4. Lightning web components

- LWC for new UI; no new Aura or Visualforce without an ADR.
- Use Lightning Data Service (`lightning-record-form`, `getRecord`, `updateRecord`) before custom Apex.
- Apex for components: `@AuraEnabled(cacheable=true)` for reads, user-mode queries, and specific error messages.

## 5. Data model

- Reuse standard objects and fields before creating custom ones.
- Every custom field has a description and help text where users see it.
- Lookups by default; master-detail only when the child can't exist without the parent and should inherit sharing.
- Consider data volume: more than about a million rows per object needs an indexing and archiving plan in the spec.

## 6. Naming (Team decision)

- API names in PascalCase with underscores between words: `Forecast_Line__c`, `Amount__c`.
- Apex classes: `<Thing>Service`, `<Thing>Selector`, `<Object>TriggerHandler`, `<Thing>Controller` for UI,
  tests `<Class>Test`.
- LWC folders in camelCase: `forecastGrid`.
- Permission sets describe a job: `Forecast_Manager`.
