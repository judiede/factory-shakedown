@IsTest
private class AccountSummaryControllerTest {
    @TestSetup
    static void makeData() {
        Account account = new Account(Name = 'Summary Test');
        insert account;
        List<Opportunity> opportunities = new List<Opportunity>();
        for (Integer i = 0; i < 200; i++) {
            opportunities.add(
                new Opportunity(
                    AccountId = account.Id,
                    Name = 'Open ' + i,
                    StageName = 'Prospecting',
                    CloseDate = Date.today().addDays(30),
                    Amount = 100
                )
            );
        }
        opportunities.add(
            new Opportunity(
                AccountId = account.Id,
                Name = 'Won',
                StageName = 'Closed Won',
                CloseDate = Date.today(),
                Amount = 1000
            )
        );
        insert opportunities;
    }

    @IsTest
    static void countsOnlyOpenOpportunities() {
        Id accountId = [SELECT Id FROM Account WHERE Name = 'Summary Test' LIMIT 1].Id;

        Test.startTest();
        AccountSummaryController.Summary summary = AccountSummaryController.getSummary(accountId);
        Test.stopTest();

        Assert.areEqual(200, summary.openCount, 'Only open opportunities are counted');
        Assert.areEqual(20000, summary.openAmount, 'Only open amounts are added up');
    }

    @IsTest
    static void returnsZeroForAnAccountWithoutOpportunities() {
        Account empty = new Account(Name = 'No Opportunities');
        insert empty;

        AccountSummaryController.Summary summary = AccountSummaryController.getSummary(empty.Id);

        Assert.areEqual(0, summary.openCount, 'No opportunities, no count');
        Assert.areEqual(0, summary.openAmount, 'No opportunities, no amount');
    }

    @IsTest
    static void rejectsAMissingAccountId() {
        try {
            AccountSummaryController.getSummary(null);
            Assert.fail('A missing account ID must be rejected');
        } catch (AuraHandledException e) {
            Assert.isNotNull(e, 'The error reaches the component');
        }
    }
}
