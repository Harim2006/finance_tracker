(function () {
    const config = window.FINANCE_API_CONFIG || {};
    const budgetUrl = (config.budgetUrl || 'http://localhost:5001').replace(/\/$/, '');
    const billsUrl = (config.billsUrl || 'http://localhost:5002').replace(/\/$/, '');
    let envelopes = [], bills = [];

    const $ = (selector) => document.querySelector(selector);
    const money = (value) => new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(Number(value || 0));
    const notify = (message, error = false) => { const node = $('#notification'); node.textContent = message; node.className = `notification show${error ? ' error' : ''}`; setTimeout(() => node.className = 'notification', 3500); };
    const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
    async function api(base, path, options = {}) {
        const readOnly = (options.method || 'GET').toUpperCase() === 'GET';
        const attempts = readOnly ? 3 : 1;
        for (let attempt = 0; attempt < attempts; attempt += 1) {
            try {
                const response = await fetch(`${base}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options });
                let body = {}; try { body = await response.json(); } catch (_) {}
                if (response.ok) return body;
                const retryable = readOnly && [502, 503, 504].includes(response.status) && attempt < attempts - 1;
                if (retryable) { await sleep(500 * (2 ** attempt)); continue; }
                if ([502, 503, 504].includes(response.status)) {
                    throw new Error('The service is temporarily unavailable while its database starts. Please try again shortly.');
                }
                throw new Error(body.error || `Request failed (${response.status})`);
            } catch (error) {
                const retryable = readOnly && error instanceof TypeError && attempt < attempts - 1;
                if (retryable) { await sleep(500 * (2 ** attempt)); continue; }
                if (error instanceof TypeError) {
                    throw new Error('The service is temporarily unavailable. Please try again shortly.');
                }
                throw error;
            }
        }
        throw new Error('The service is temporarily unavailable. Please try again shortly.');
    }
    const json = (method, data) => ({ method, body: JSON.stringify(data) });
    function showPage() { const page = (location.hash || '#dashboard').slice(1); document.querySelectorAll('.page-section').forEach(section => section.classList.toggle('active', section.id === page)); }
    function showEmpty(node, message) { node.innerHTML = `<p class="empty">${message}</p>`; }
    function renderEnvelopes() {
        const list = $('#envelopes-list');
        if (!envelopes.length) return showEmpty(list, 'No envelopes yet. Add your first envelope to start budgeting.');
        list.innerHTML = envelopes.map((e) => { const allocation = Number(e.monthly_allocation || 0); const balance = Number(e.current_balance || 0); const percent = allocation > 0 ? Math.min(100, Math.max(0, balance / allocation * 100)) : 0; return `<article class="envelope-card"><h3>${escapeHtml(e.name)}</h3><span class="muted">Monthly allocation ${money(allocation)}</span><div class="balance">${money(balance)}</div><div class="progress"><span class="${balance < 0 ? 'over' : ''}" style="width:${percent}%"></span></div><span class="muted">${balance < 0 ? 'Overspent' : `${Math.round(percent)}% remaining`}</span><div style="margin-top:.8rem;display:flex;gap:.5rem"><button class="button small" data-envelope-action="allocate" data-id="${e.id}">Allocate</button><button class="button small secondary" data-envelope-action="spend" data-id="${e.id}">Record expense</button></div></article>`; }).join('');
        $('#dashboard-envelopes').innerHTML = `<table><thead><tr><th>Envelope</th><th>Budget</th><th>Balance</th></tr></thead><tbody>${envelopes.slice(0, 5).map(e => `<tr><td>${escapeHtml(e.name)}</td><td>${money(e.monthly_allocation)}</td><td>${money(e.current_balance)}</td></tr>`).join('')}</tbody></table>`;
    }
    function renderBills() {
        const list = $('#bills-list'); $('#bill-count').textContent = `${bills.length} active`;
        if (!bills.length) return showEmpty(list, 'No bills tracked yet. Add your first recurring bill.');
        list.innerHTML = `<table><thead><tr><th>Name</th><th>Amount</th><th>Frequency</th><th>Next due</th><th>Category</th><th>Actions</th></tr></thead><tbody>${bills.map(b => `<tr><td><strong>${escapeHtml(b.name)}</strong></td><td>${money(b.amount)}</td><td>${escapeHtml(b.frequency)}</td><td>${escapeHtml(b.next_due_date || '')}</td><td>${escapeHtml(b.category || 'other')}</td><td><button class="button small" data-bill-action="pay" data-id="${b.id}" data-amount="${b.amount}">Mark paid</button> <button class="button small danger" data-bill-action="deactivate" data-id="${b.id}">Deactivate</button></td></tr>`).join('')}</tbody></table>`;
        $('#dashboard-bills').innerHTML = `<table><thead><tr><th>Bill</th><th>Amount</th><th>Due</th></tr></thead><tbody>${bills.slice(0, 5).map(b => `<tr><td>${escapeHtml(b.name)}</td><td>${money(b.amount)}</td><td>${escapeHtml(b.next_due_date || '')}</td></tr>`).join('')}</tbody></table>`;
    }
    async function refresh() { try { [envelopes, bills] = await Promise.all([api(budgetUrl, '/envelopes'), api(billsUrl, '/bills')]); const summary = await api(budgetUrl, '/api/dashboard/summary'); $('#total-allocated').textContent = money(summary.total_allocated); $('#spent-month').textContent = money(summary.spent_this_month); $('#upcoming-bills').textContent = money(summary.upcoming_bills_30days); renderEnvelopes(); renderBills(); loadInsights(); } catch (error) { notify(error.message, true); } }
    async function loadInsights() { try { const data = await api(budgetUrl, '/analysis/insights'); $('#insights').innerHTML = (data.insights || []).map(i => { const insight = typeof i === 'string' ? { message: i } : i; return `<li><strong>${escapeHtml(insight.title || 'Insight')}:</strong> ${escapeHtml(insight.message || '')}</li>`; }).join(''); } catch (_) { $('#insights').innerHTML = ''; } }
    function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;' }[c])); }
    async function submitForm(event, path, base, success) { event.preventDefault(); const form = event.target; try { const data = Object.fromEntries(new FormData(form)); if (data.amount) data.amount = Number(data.amount); if (data.monthly_allocation) data.monthly_allocation = Number(data.monthly_allocation); if (data.due_day) data.due_day = Number(data.due_day); await api(base, path, json('POST', data)); form.reset(); form.closest('dialog')?.close(); notify(success); await refresh(); } catch (error) { notify(error.message, true); } }
    document.addEventListener('click', async (event) => { const modal = event.target.dataset.modal; if (modal) $(`#${modal}`).showModal(); if (event.target.matches('[data-close]')) event.target.closest('dialog').close(); if (event.target.dataset.action === 'refresh') refresh(); if (event.target.dataset.action === 'rollover') { try { await api(budgetUrl, '/envelopes/rollover', json('POST', {})); notify('Monthly rollover completed'); refresh(); } catch (e) { notify(e.message, true); } } const envelopeAction = event.target.dataset.envelopeAction; if (envelopeAction) { const id = event.target.dataset.id; const amount = prompt(envelopeAction === 'allocate' ? 'Amount to allocate:' : 'Expense amount:'); if (amount === null) return; const data = { amount: Number(amount) }; if (envelopeAction === 'spend') { data.merchant = prompt('Merchant (optional):') || ''; data.description = prompt('Description (optional):') || ''; } try { await api(budgetUrl, `/envelopes/${id}/${envelopeAction}`, json('POST', data)); notify('Envelope updated'); refresh(); } catch (e) { notify(e.message, true); } } const billAction = event.target.dataset.billAction; if (billAction) { const id = event.target.dataset.id; try { if (billAction === 'pay') await api(billsUrl, `/bills/${id}/pay`, json('POST', { amount_paid: Number(event.target.dataset.amount), payment_date: new Date().toISOString().slice(0, 10) })); else if (confirm('Deactivate this bill?')) await api(billsUrl, `/bills/${id}/deactivate`, json('POST', {})); notify(billAction === 'pay' ? 'Payment recorded' : 'Bill deactivated'); refresh(); } catch (e) { notify(e.message, true); } } });
    $('#envelope-form').addEventListener('submit', e => submitForm(e, '/envelopes/create', budgetUrl, 'Envelope created')); $('#bill-form').addEventListener('submit', e => submitForm(e, '/bills/create', billsUrl, 'Bill created'));
    $('#purchase-form').addEventListener('submit', e => submitForm(e, '/simulate-purchase', budgetUrl, 'Purchase recorded')); $('#question-form').addEventListener('submit', async e => { e.preventDefault(); try { const data = await api(budgetUrl, '/analysis/ask', json('POST', { question: new FormData(e.target).get('question') })); $('#answer').textContent = data.answer; e.target.reset(); } catch (error) { notify(error.message, true); } });
    window.addEventListener('hashchange', () => { showPage(); refresh(); }); showPage(); refresh();
}());
