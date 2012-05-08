import pymongo, bson
QUERY = {'deleted': False}
FIELDS = [
    'document_id',
    'docket_id',
    'agency',
    'title',
    'details.fr_publish_date',
    'details.comment_start_date',
    'details.comment_end_date',
    'type',
    'views.entities',
    'attachments.views.entities',
    'submitter_entities'
]

# class to work around the mincemeat requirement that the data be structured as a dictionary
class MongoSource(object):
    def __init__(self, db):
        self.cache = {}
        self.db = db

    def __iter__(self):
        _cache = self.cache

        def gen():
            for doc in self.db.docs.find(QUERY, FIELDS):
                doc_id = str(doc['_id'])
                _cache[doc_id] = doc
                yield doc_id

        return gen()

    def __getitem__(self, key):
        out = self.cache[key]
        del self.cache[key]
        return out


def mapfn(key, document):
    import isoweek
    from collections import defaultdict
    import itertools

    # pre-computed date data
    doc_type = document.get('type', None)
    details = document.get('details', {})
    doc_date = details.get('fr_publish_date', None)
    doc_week = isoweek.Week(*(doc_date.isocalendar()[:-1])) if doc_date else None
    doc_week_range = (doc_week.monday().isoformat(), doc_week.sunday().isoformat()) if doc_week else None
    doc_month = doc_date.isoformat()[:7] if doc_date else None
    
    if 'comment_start_date' in details and 'comment_end_date' in details:
        comment_date_range = [details['comment_start_date'].date().isoformat(), details['comment_end_date'].date().isoformat()]
    else:
        comment_date_range = None

    ### COLLECTION: dockets ###
    docket_info = {
        'count': 1,
        'type_breakdown': {str(doc_type): 1},
        'fr_docs': [{
            'date': doc_date.date().isoformat() if doc_date else None,
            'comment_date_range': comment_date_range,
            'type': doc_type,
            'id': document['document_id'],
            'title': document['title']
        }] if doc_type in ['notice', 'rule', 'proposed_rule'] else [],
        'weeks': [(doc_week_range, 1)],
        'date_range': [doc_date, doc_date],
        'text_entities': {},
        'submitter_entities': {}
    }

    ### COLLECTION: agencies ###
    agency_info = {
        'count': 1,
        'date_range': [doc_date, doc_date],
        'months': [(doc_month, 1)],
        'type_breakdown': {str(doc_type): 1},
        'text_entities': {},
        'submitter_entities': {}
    }

    # entity data for dockets and agencies
    # text entities
    views = itertools.chain.from_iterable([document.get('views', [])] + [attachment.get('views', []) for attachment in document.get('attachments', [])])
    for view in views:
        for entity in view.get('entities', []):
            docket_info['text_entities'][entity] = 1
            agency_info['text_entities'][entity] = 1

    # submitters
    for entity in document.get('submitter_entities', []):
        docket_info['submitter_entities'][entity] = 1
        agency_info['submitter_entities'][entity] = 1

    yield ('dockets', document['docket_id']), docket_info
    yield ('agencies', document.get('agency', None)), agency_info

    ### COLLECTION: entities ###
    entities = set(docket_info['text_entities'].keys())
    entities.update(docket_info['submitter_entities'].keys())

    for entity in entities:
        text_count = docket_info['text_entities'].get(entity, 0)
        submitter_count = docket_info['submitter_entities'].get(entity, 0)
        
        entity_info = {
            'text_mentions': {
                'count': text_count,
                'agencies': {document.get('agency', None): text_count},
                'dockets': {document['docket_id']: text_count},
                'months': [(doc_month, text_count)],
                'date_range': [doc_date, doc_date] if text_count else [None, None]
            },
            'submitter_mentions': {
                'count': submitter_count,
                'agencies': {document.get('agency', None): submitter_count},
                'dockets': {document['docket_id']: submitter_count},
                'months': [(doc_month, submitter_count)],
                'date_range': [doc_date, doc_date] if submitter_count else [None, None]
            }
        }
        yield ('entities', entity), entity_info


def reducefn(key, documents):
    from collections import defaultdict
    import datetime

    def min_date(*args):
        a = [arg for arg in args if arg is not None]
        if not a:
            return None
        else:
            return min(a)

    def max_date(*args):
        a = [arg for arg in args if arg is not None]
        if not a:
            return None
        else:
            return max(a)

    ### COLLECTION: dockets ###
    if key[0] == 'dockets':
        out = {
            'count': 0,
            'type_breakdown': defaultdict(int),
            'fr_docs': [],
            'weeks': defaultdict(int),
            'date_range': [None, None],
            'text_entities': defaultdict(int),
            'submitter_entities': defaultdict(int)
        }
        if documents:
            out['date_range'] = documents[0]['date_range']

        for value in documents:
            out['count'] += value['count']
            
            for doc_type, count in value['type_breakdown'].iteritems():
                out['type_breakdown'][doc_type] += count
            
            out['fr_docs'].extend(value['fr_docs'])
            
            for week, count in dict(value['weeks']).iteritems():
                out['weeks'][week] += count

            for entity, count in value['text_entities'].iteritems():
                out['text_entities'][entity] += count

            for entity, count in value['submitter_entities'].iteritems():
                out['submitter_entities'][entity] += count

            out['date_range'][0] = min_date(out['date_range'][0], value['date_range'][0])
            out['date_range'][1] = max_date(out['date_range'][1], value['date_range'][1])

        out['fr_docs'] = sorted(out['fr_docs'], key=lambda x: x['date'])

        out['weeks'] = sorted(out['weeks'].items(), key=lambda x: x[0][0] if x[0] else datetime.date.min.isoformat())
        return out

    ### COLLECTION: agencies ###
    if key[0] == 'agencies':
        out = {
            'count': 0,
            'type_breakdown': defaultdict(int),
            'months': defaultdict(int),
            'date_range': [None, None],
            'text_entities': defaultdict(int),
            'submitter_entities': defaultdict(int)
        }
        if documents:
            out['date_range'] = documents[0]['date_range']

        for value in documents:
            out['count'] += value['count']
            
            for doc_type, count in value['type_breakdown'].iteritems():
                out['type_breakdown'][doc_type] += count
                        
            for month, count in dict(value['months']).iteritems():
                out['months'][month] += count

            for entity, count in value['text_entities'].iteritems():
                out['text_entities'][entity] += count

            for entity, count in value['submitter_entities'].iteritems():
                out['submitter_entities'][entity] += count

            out['date_range'][0] = min_date(out['date_range'][0], value['date_range'][0])
            out['date_range'][1] = max_date(out['date_range'][1], value['date_range'][1])

        out['months'] = sorted(out['months'].items(), key=lambda x: x[0] if x[0] else datetime.date.min.isoformat())
        return out

    ### COLLECTION: entities ###
    elif key[0] == 'entities':
        out = {
            'text_mentions': {
                'count': 0,
                'agencies': defaultdict(int),
                'dockets': defaultdict(int),
                'months': defaultdict(int),
                'date_range': [None, None]
            },
            'submitter_mentions': {
                'count': 0,
                'agencies': defaultdict(int),
                'dockets': defaultdict(int),
                'months': defaultdict(int),
                'date_range': [None, None]
            }
        }
        for value in documents:
            for mention_type in ['text_mentions', 'submitter_mentions']:
                out[mention_type]['count'] += value[mention_type]['count']
                for agency, count in value[mention_type]['agencies'].iteritems():
                    if value[mention_type]['agencies'][agency]:
                        out[mention_type]['agencies'][agency] += value[mention_type]['agencies'][agency]
                for docket, count in value[mention_type]['dockets'].iteritems():
                    if value[mention_type]['dockets'][docket]:
                        out[mention_type]['dockets'][docket] += value[mention_type]['dockets'][docket]
                months_dict = dict(value[mention_type]['months'])
                for month, count in months_dict.iteritems():
                    if months_dict[month]:
                        out[mention_type]['months'][month] += months_dict[month]
                out[mention_type]['date_range'][0] = min_date(out[mention_type]['date_range'][0], value[mention_type]['date_range'][0])
                out[mention_type]['date_range'][1] = max_date(out[mention_type]['date_range'][1], value[mention_type]['date_range'][1])

        for mention_type in ['text_mentions', 'submitter_mentions']:
            out[mention_type]['months'] = sorted(out[mention_type]['months'].items(), key=lambda x: x[0] if x[0] else datetime.date.min.isoformat())
        
        return out

if __name__ == '__main__':
    db = pymongo.Connection().regulations

    import mincemeat
    s = mincemeat.SqliteServer('/tmp/test.db')
    s.mapfn = mapfn
    s.reducefn = reducefn
    s.datasource = MongoSource(db)

    results = s.run_server()

    for key, value in results:
        collection = key[0]
        _id = key[1]
        if not _id:
            continue

        try:
            db[collection].update(
                {
                    '_id': _id
                },
                {
                    '$set': {'stats': value}
                },
                upsert=True,
                safe=True
            )
        except bson.errors.InvalidDocument:
            print value
            raise