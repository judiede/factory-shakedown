import { LightningElement, api, wire } from 'lwc';
import getSummary from '@salesforce/apex/AccountSummaryController.getSummary';

export default class AccountSummary extends LightningElement {
    @api recordId;
    summary;
    error;

    @wire(getSummary, { accountId: '$recordId' })
    wiredSummary({ data, error }) {
        if (data) {
            this.summary = data;
            this.error = undefined;
        } else if (error) {
            this.summary = undefined;
            this.error = error.body && error.body.message ? error.body.message : 'The summary could not be loaded.';
        }
    }
}
