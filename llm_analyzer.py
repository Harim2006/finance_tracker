"""
LLM-powered Financial Analysis and Q&A
Provides insights and answers questions about user's financial data
"""
from datetime import date, datetime, timedelta
import json
from datetime import datetime
from datetime import date


class FinanceLLMAnalyzer:
    """
    Simulated LLM analyzer for financial insights and Q&A
    
    In production, this would integrate with OpenAI API, Anthropic Claude, etc.
    For this assignment (no external services), we implement rule-based analysis
    that mimics LLM behavior.
    """
    
    def __init__(self):
        self.insights_cache = {}
    
    
    def analyze_and_answer(self, question, context):
        """
        Answer a user question about their finances
        
        Args:
            question: User's question (string)
            context: Dict with envelopes, bills, transactions data
            
        Returns:
            Answer string
        """
        question_lower = question.lower()
        
        # Pattern matching for common question types
        if 'overspending' in question_lower or 'over budget' in question_lower:
            return self._analyze_overspending(context)
        
        elif 'save' in question_lower or 'saving' in question_lower:
            return self._suggest_savings(context)
        
        elif 'bill' in question_lower and ('when' in question_lower or 'due' in question_lower):
            return self._summarize_upcoming_bills(context)
        
        elif 'spend' in question_lower and 'most' in question_lower:
            return self._identify_top_spending(context)
        
        elif 'afford' in question_lower:
            return self._assess_affordability(context, question)
        
        elif 'budget' in question_lower and 'recommend' in question_lower:
            return self._recommend_budget_changes(context)
        
        else:
            return self._general_financial_summary(context)
    
    
    def _analyze_overspending(self, context):
        """Identify which envelopes are overspent"""
        envelopes = context.get('envelopes', [])
        overspent = [e for e in envelopes if e['current_balance'] < 0]
        
        if not overspent:
            return "Good news! You're not overspending in any category right now. All your envelopes have positive balances."
        
        analysis = "You're currently overspending in the following categories:\n\n"
        
        for env in overspent:
            amount = abs(env['current_balance'])
            analysis += f"• **{env['name']}**: ${amount:.2f} over budget\n"
        
        total_overspent = sum(abs(e['current_balance']) for e in overspent)
        
        analysis += f"\n**Total overspending**: ${total_overspent:.2f}\n\n"
        analysis += "**Recommendation**: Consider reducing spending in these categories or reallocating funds from envelopes with surplus."
        
        return analysis
    
    
    def _suggest_savings(self, context):
        """Suggest ways to save money"""
        envelopes = context.get('envelopes', [])
        transactions = context.get('recent_transactions', [])
        
        suggestions = "Here are some savings opportunities I've identified:\n\n"
        
        # Find envelopes with surplus
        surplus_envelopes = [e for e in envelopes if e['current_balance'] > e['monthly_allocation']]
        
        if surplus_envelopes:
            suggestions += "**Unused Budget**:\n"
            for env in surplus_envelopes[:3]:
                surplus = env['current_balance'] - env['monthly_allocation']
                suggestions += f"• {env['name']}: ${surplus:.2f} surplus - consider reducing monthly allocation\n"
            suggestions += "\n"
        
        # Analyze transaction frequency
        if transactions:
            merchant_spending = {}
            for txn in transactions:
                merchant = txn.get('merchant', 'Unknown')
                merchant_spending[merchant] = merchant_spending.get(merchant, 0) + txn['amount']
            
            # Find top merchants
            top_merchants = sorted(merchant_spending.items(), key=lambda x: x[1], reverse=True)[:3]
            
            suggestions += "**Top Spending Merchants**:\n"
            for merchant, amount in top_merchants:
                suggestions += f"• {merchant}: ${amount:.2f}\n"
            suggestions += "\nConsider if you can reduce frequency or find alternatives.\n\n"
        
        suggestions += "**General Tips**:\n"
        suggestions += "• Review subscriptions - are you using all of them?\n"
        suggestions += "• Compare bills to market rates (insurance, internet, etc.)\n"
        suggestions += "• Set up automatic transfers to savings when envelopes have surplus"
        
        return suggestions
    
    
    def _summarize_upcoming_bills(self, context):
        """Summarize upcoming bills"""
        bills = context.get('bills', [])
        
        if not bills:
            return "You don't have any bills tracked yet."
        
        from datetime import datetime, timedelta
        today = datetime.now().date()
        next_30_days = today + timedelta(days=30)
        
        upcoming = [
            b for b in bills
            if b.get('next_due_date')
            and self._as_date(b['next_due_date']) <= next_7_days
        ]
        
        if not upcoming:
            return "No bills are due in the next 30 days."
        
        summary = "**Upcoming Bills (Next 30 Days)**:\n\n"
        
        # Sort by date
        upcoming.sort(key=lambda b: b['next_due_date'])
        
        total = 0
        for bill in upcoming:
            due_date = datetime.fromisoformat(bill['next_due_date']).strftime('%b %d')
            summary += f"• **{bill['name']}**: ${bill['amount']:.2f} - Due {due_date}\n"
            total += bill['amount']
        
        summary += f"\n**Total due in next 30 days**: ${total:.2f}"
        
        return summary
    
    
    def _identify_top_spending(self, context):
        """Identify top spending categories"""
        transactions = context.get('recent_transactions', [])
        
        if not transactions:
            return "No recent transactions to analyze."
        
        # Group by envelope
        envelope_spending = {}
        for txn in transactions:
            envelope = txn.get('envelope_name', 'Uncategorized')
            envelope_spending[envelope] = envelope_spending.get(envelope, 0) + txn['amount']
        
        # Sort by amount
        top_categories = sorted(envelope_spending.items(), key=lambda x: x[1], reverse=True)
        
        analysis = "**Your Top Spending Categories (Last 30 Days)**:\n\n"
        
        total_spent = sum(envelope_spending.values())
        
        for i, (envelope, amount) in enumerate(top_categories[:5], 1):
            percentage = (amount / total_spent * 100) if total_spent > 0 else 0
            analysis += f"{i}. **{envelope}**: ${amount:.2f} ({percentage:.1f}%)\n"
        
        analysis += f"\n**Total spending**: ${total_spent:.2f}"
        
        return analysis
    
    
    def _assess_affordability(self, context, question):
        """Assess if user can afford something"""
        import re
        amount_match = re.search(r'\$?(\d+(?:\.\d{2})?)', question)
        
        if not amount_match:
            return "Please specify an amount. For example: 'Can I afford a $50 purchase?'"
        
        amount = float(amount_match.group(1))
        
        envelopes = context.get('envelopes', [])
        bills = context.get('bills', [])
        
        # Calculate available funds
        total_available = sum(e['current_balance'] for e in envelopes if e['current_balance'] > 0)
        
        # Calculate upcoming bills
        from datetime import datetime, timedelta
        today = datetime.now().date()
        next_30_days = today + timedelta(days=30)
        
        upcoming_bills_total = sum(
            b['amount'] for b in bills 
            if b.get('next_due_date') and self._as_date(b['next_due_date']) <= next_30_days
        )
        
        # Calculate truly available (after bills)
        available_after_bills = total_available - upcoming_bills_total
        
        if available_after_bills >= amount:
            return f"✅ **Yes, you can afford it!**\n\nYou have ${total_available:.2f} available. After accounting for ${upcoming_bills_total:.2f} in upcoming bills, you'll have ${available_after_bills:.2f} remaining, which covers the ${amount:.2f} purchase.\n\n**Recommendation**: Make sure to categorize this purchase to the appropriate envelope."
        else:
            shortfall = amount - available_after_bills
            return f"⚠️ **Caution - This might stretch your budget.**\n\nYou have ${total_available:.2f} available, but ${upcoming_bills_total:.2f} in upcoming bills. After bills, you'll only have ${available_after_bills:.2f}, which is ${shortfall:.2f} short of the ${amount:.2f} purchase.\n\n**Recommendation**: Consider waiting or reducing spending in another category first."
    
    
    def _recommend_budget_changes(self, context):
        """Recommend budget allocation changes"""
        envelopes = context.get('envelopes', [])
        
        recommendations = "**Budget Allocation Recommendations**:\n\n"
        
        # Find consistently overspent envelopes
        overspent = [e for e in envelopes if e['current_balance'] < 0]
        
        if overspent:
            recommendations += "**Increase allocations for**:\n"
            for env in overspent:
                shortage = abs(env['current_balance'])
                recommended = env['monthly_allocation'] + shortage
                recommendations += f"• {env['name']}: ${env['monthly_allocation']:.2f} → ${recommended:.2f}\n"
            recommendations += "\n"
        
        # Find consistently under-spent envelopes
        underused = [e for e in envelopes if e['current_balance'] > e['monthly_allocation'] * 1.5]
        
        if underused:
            recommendations += "**Consider reducing allocations for**:\n"
            for env in underused:
                surplus = env['current_balance'] - env['monthly_allocation']
                recommended = env['monthly_allocation'] * 0.8
                recommendations += f"• {env['name']}: ${env['monthly_allocation']:.2f} → ${recommended:.2f} (current surplus: ${surplus:.2f})\n"
            recommendations += "\n"
        
        if not overspent and not underused:
            recommendations += "Your budget allocations look well-balanced! No major adjustments needed.\n\n"
        
        recommendations += "**Tip**: Review and adjust allocations monthly based on actual spending patterns."
        
        return recommendations
    
    
    def _general_financial_summary(self, context):
        """Provide general financial overview"""
        envelopes = context.get('envelopes', [])
        bills = context.get('bills', [])
        transactions = context.get('recent_transactions', [])
        
        summary = "**Financial Overview**:\n\n"
        
        # Total allocated
        total_budget = sum(e['monthly_allocation'] for e in envelopes)
        total_balance = sum(e['current_balance'] for e in envelopes)
        
        summary += f"• **Total Monthly Budget**: ${total_budget:.2f}\n"
        summary += f"• **Current Balance**: ${total_balance:.2f}\n"
        
        # Spending rate
        total_spent = sum(txn['amount'] for txn in transactions)
        summary += f"• **Spent (Last 30 Days)**: ${total_spent:.2f}\n\n"
        
        # Bill summary
        total_bills = sum(b['amount'] for b in bills)
        summary += f"• **Recurring Bills**: ${total_bills:.2f}/month across {len(bills)} bills\n\n"
        
        # Health check
        if total_balance < total_budget * 0.3:
            summary += "⚠️ **Alert**: Your balance is running low. Consider reducing discretionary spending.\n"
        elif total_balance > total_budget * 1.5:
            summary += "✅ **Great job**: You have a healthy surplus! Consider increasing savings or investments.\n"
        else:
            summary += "✅ **Status**: Your finances look healthy and balanced.\n"
        
        return summary
    
    
    @staticmethod
    def _as_date(value):
        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        return datetime.fromisoformat(value).date()
    
    def generate_insights(self, context):
        """Generate automated insights"""
        insights = []
        
        envelopes = context.get('envelopes', [])
        bills = context.get('bills', [])
        
        # Check for overspending
        overspent = [e for e in envelopes if e['current_balance'] < 0]
        if overspent:
            insights.append({
                'type': 'warning',
                'title': 'Overspending Detected',
                'message': f"{len(overspent)} envelope(s) are over budget. Review spending in: {', '.join(e['name'] for e in overspent[:3])}"
            })
        
        # Check for upcoming bills
        from datetime import datetime, timedelta
        today = datetime.now().date()
        next_7_days = today + timedelta(days=7)
        
        upcoming = [
           b for b in bills
           if b.get('next_due_date')
           and self._as_date(b['next_due_date']) <= next_7_days
        ]
        
        if upcoming:
            total_due = sum(b['amount'] for b in upcoming)
            insights.append({
                'type': 'info',
                'title': 'Bills Due Soon',
                'message': f"${total_due:.2f} in bills due within 7 days. Make sure you have funds available."
            })
        
        # Positive feedback
        healthy = [e for e in envelopes if e['current_balance'] > 0 and e['current_balance'] >= e['monthly_allocation'] * 0.5]
        if len(healthy) >= len(envelopes) * 0.7:
            insights.append({
                'type': 'success',
                'title': 'Good Financial Health',
                'message': f"{len(healthy)} out of {len(envelopes)} envelopes are healthy. Keep up the good work!"
            })
        
        return insights