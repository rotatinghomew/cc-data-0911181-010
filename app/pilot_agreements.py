from .storage import DataError


def sign(store,journal,payload):
    with journal.transaction():
        grant=journal.get('pilot_fund',payload['recommendation'])
        school=store.find('pilot_schools',school=payload['school'])
        if school['region']!=grant['region'] or grant['status']!='approved':
            raise DataError('school outside approved pilot')
        key=grant['recommendation']+':'+school['school']
        prior=[row for row in journal.all('pilot_agreement') if row['agreement']==key]
        if prior:
            return prior[0]
        return journal.put('pilot_agreement',key,dict(agreement=key,school=school['school'],
                           recommendation=grant['recommendation'],scope=grant['scope'],amount=grant['amount'],status='signed'))
