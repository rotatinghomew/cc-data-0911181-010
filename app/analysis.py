from .domain import effect_record
from .storage import DataError, single
from . import synthesis


def catalog(store,query):
    institution=single(query,'institution')
    studies=[row for row in store.table('studies')
             if institution is None or row['institution']==institution]
    return {'studies':[dict(row,effects=[effect_record(store,effect) for effect in
                                         store.select('effects',study=row['study'])]) for row in studies]}


def evidence(store,query):
    return {'effects':[effect_record(store,row) for row in store.table('effects')],
            'publications':store.table('publications'),'decisions':store.table('decisions'),
            'synthesis':synthesis.synthesize(store)}


def synthesis_view(store,query):
    service=single(query,'service')
    exclude_institution=single(query,'exclude_institution')
    raw=single(query,'correlation')
    grid=None
    if raw is not None:
        try:
            assumed=float(raw)
        except ValueError:
            raise DataError('number required: correlation') from None
        if not 0<=assumed<1:
            raise DataError('correlation must be in [0, 1)')
        grid=sorted({0.0,assumed,0.9})
    return synthesis.synthesize(store,service=service,exclude_institution=exclude_institution,grid=grid)


ROUTES={'/api/catalog':catalog,'/api/evidence':evidence,'/api/synthesis':synthesis_view}
