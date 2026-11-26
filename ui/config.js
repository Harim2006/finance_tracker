// Direct API origins for a standalone static server. The Nginx image replaces
// this file with config.compose.js and uses same-origin reverse-proxy paths.
window.FINANCE_API_CONFIG = {
    budgetUrl: 'http://localhost:5001',
    billsUrl: 'http://localhost:5002'
};
