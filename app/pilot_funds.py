from .storage import DataError


def approve(store,journal,payload):
    with journal.transaction():
        recommendation=journal.get('recommendation',payload['recommendation'])
        region=store.find('regions',region=recommendation['region'])
        amount=float(payload['amount'])
        prior=[row for row in journal.all('pilot_fund') if row['recommendation']!=recommendation['recommendation']
               and row['region']==region['region']]
        if amount<=0 or amount+sum(row['amount'] for row in prior)>region['budget']:
            raise DataError('pilot funding limit exceeded')
        row=dict(recommendation=recommendation['recommendation'],region=region['region'],scope=recommendation['scope'],
                 amount=amount,status='approved')
        return journal.put('pilot_fund',row['recommendation'],row)
