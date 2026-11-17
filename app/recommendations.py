def propose(store,journal,payload):
    region=store.find('regions',region=payload['region'])
    studies=sorted(set(payload['studies']))
    for study in studies:
        store.find('studies',study=study)
    row=dict(recommendation=payload['recommendation'],region=region['region'],studies=studies,
             scope=payload['scope'],status='proposed')
    with journal.transaction():
        return journal.put('recommendation',row['recommendation'],row)
