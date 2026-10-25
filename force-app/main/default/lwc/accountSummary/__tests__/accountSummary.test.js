import { createElement } from 'lwc';
import AccountSummary from 'c/accountSummary';
import getSummary from '@salesforce/apex/AccountSummaryController.getSummary';

jest.mock(
    '@salesforce/apex/AccountSummaryController.getSummary',
    () => {
        const { createApexTestWireAdapter } = require('@salesforce/sfdx-lwc-jest');
        return { default: createApexTestWireAdapter(jest.fn()) };
    },
    { virtual: true }
);

describe('c-account-summary', () => {
    afterEach(() => {
        while (document.body.firstChild) {
            document.body.removeChild(document.body.firstChild);
        }
        jest.clearAllMocks();
    });

    function render() {
        const element = createElement('c-account-summary', { is: AccountSummary });
        element.recordId = '001000000000000AAA';
        document.body.appendChild(element);
        return element;
    }

    it('shows the number of open opportunities', async () => {
        const element = render();
        getSummary.emit({ openCount: 3, openAmount: 1500 });
        await Promise.resolve();

        expect(element.shadowRoot.querySelector('.open-count').textContent).toBe('Open opportunities: 3');
    });

    it('shows the error message when the summary cannot load', async () => {
        const element = render();
        getSummary.error({ message: 'You do not have access to opportunities.' });
        await Promise.resolve();

        expect(element.shadowRoot.querySelector('.error').textContent).toBe('You do not have access to opportunities.');
    });
});
