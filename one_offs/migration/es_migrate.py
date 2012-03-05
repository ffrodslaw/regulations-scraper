#!/usr/bin/env python

SERVER = '10.241.118.127:9200'

from pymongo import Connection
import urllib2, json, traceback, datetime, zlib

def get_text(view):
    text = view.get('text', None)
    if not text:
        return None
    
    if type(text) == dict and 'compressed' in text:
        print 'decompressing document'
        return zlib.decompress(text['compressed'])
    else:
        return text

db = Connection().regulations

import pyes

es = pyes.ES(['10.241.118.127:9500'])

now = datetime.datetime.now()
for doc in db.docs.find({'deleted': False, 'scraped': True}):
    print 'trying', doc['document_id']
    if 'renamed_to' in doc:
        print 'renamed', doc['document_id']
        continue
    
    # build initial ES document
    es_doc = {
        'document_id': doc['document_id'],
        'docket_id': doc['document_id'],
        'title': doc['title'],
        'agency': doc['agency'],
        'posted_date': doc['details'].get('fr_publish_date', None),
        'submitter_organization': doc['details'].get('organization', None),
        'submitter_name': ' '.join(filter(bool, [doc['details'].get('first_name', None), doc['details'].get('mid_initial', None), doc['details'].get('last_name', None)])),
        'files': []
    }

    # add views
    for view in doc.get('views', []):
        if not view.get("text", False):
            continue
        es_doc['files'].append({
            "title": None,
            "abstract": None,
            "object_id": doc['object_id'],
            "file_type": view['type'],
            "text": get_text(view)
        })

    # add attachments
    for attachment in doc.get('attachments', []):
        for view in attachment.get('views', []):
            if not view.get("text", False):
                continue
            es_doc['files'].append({
                "title": attachment.get('title', None),
                "abstract": attachment.get('abstract', None),
                "object_id": attachment['object_id'],
                "file_type": view['type'],
                "text": get_text(view)
            })

    # save to es
    es_status = es.index(es_doc, 'regulations', 'document')
    es_id = es_status['_id']
    print 'saved %s to ES as %s' % (doc['document_id'], es_id)

    # update main mongo doc
    doc['es_id'] = es_id
    doc['es_indexed'] = now

    # update mongo views
    for view in doc.get('views', []):
        if not view.get("text", False):
            continue
        view['es_address'] = "%s/%s.%s" % (es_id, doc['object_id'], view['type'])

    # update mongo attachments attachments
    for attachment in doc.get('attachments', []):
        for view in attachment.get('views', []):
            if not view.get("text", False):
                continue
            view['es_address'] = "%s/%s.%s" % (es_id, attachment['object_id'], view['type'])

    # save back to Mongo
    db.docs.save(doc)
    print "saved %s back to mongo" % doc['document_id']