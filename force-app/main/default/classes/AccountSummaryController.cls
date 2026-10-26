/**
 * Summary figures for the Account page card: how many opportunities are open and what they are worth.
 * Runs in user mode, so people only see opportunities they have access to.
 */
public with sharing class AccountSummaryController {
    /**
     * Counts the account's open opportunities and adds up their amounts.
     * @param accountId the account shown on the page
     * @return the open opportunity count and the open amount, 0 when there are none
     */
    @AuraEnabled(cacheable=true)
    public static Summary getSummary(Id accountId) {
        if (accountId == null) {
            throw new AuraHandledException('An account ID is required.');
        }
        AggregateResult[] rows = [
            SELECT COUNT(Id) openCount, SUM(Amount) openAmount
            FROM Opportunity
            WHERE AccountId = :accountId AND IsClosed = FALSE
            WITH USER_MODE
        ];
        Summary result = new Summary();
        result.openCount = (Integer) rows[0].get('openCount');
        Decimal amount = (Decimal) rows[0].get('openAmount');
        result.openAmount = amount == null ? 0 : amount;
        return result;
    }

    /**
     * The figures the account summary card shows.
     */
    public class Summary {
        @AuraEnabled
        public Integer openCount;
        @AuraEnabled
        public Decimal openAmount;
    }
}
