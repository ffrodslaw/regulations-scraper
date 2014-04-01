import urllib2
import json
from regs_common.util import listify

from settings import RDG_API_KEY, DDG_API_KEY
ARG_NAMES = {
    'agency': 'a',
    'docket': 'dktid'
}

def _v1_search(per_page, position, **args):
    url_args = {
        'api_key': RDG_API_KEY,
        'rpp': per_page,
        'po': position
    }

    for key, value in args.items():
        url_args[ARG_NAMES[key]] = value
    
    return urllib2.urlopen(
        "http://regulations.gov/api/documentsearch/v1.json?" + '&'.join(['%s=%s' % arg for arg in url_args.items()])
    )

def _v3_search(per_page, position, **args):
    url_args = {
        'api_key': DDG_API_KEY,
        'rpp': per_page,
        'po': position
    }

    for key, value in args.items():
        url_args[ARG_NAMES[key]] = value
    
    url = "http://api.data.gov/regulations/beta/documents.json?" + '&'.join(['%s=%s' % arg for arg in url_args.items()])
    req = urllib2.Request(url, headers={'Accept': 'application/json,*/*'})
    return urllib2.urlopen(req)

search = _v3_search

def parse(file):
    data = open(file) if type(file) in (unicode, str) else file
    return json.load(data)

def _v1_iter_parse(file):
    data = parse(file)
    return iter(listify(data['searchresult']['documents']['document']))

def _v3_iter_parse(file):
    data = parse(file)
    return iter(data['documents'])

iter_parse = _v3_iter_parse

# convenience function that strings them together
def parsed_search(per_page, position, client=None, **args):
    return parse(search(per_page, position, **args))

# use the search with an overridden client to get the agencies instead of the documents
def get_agencies():
    raise Exception("Haven't written this one yet")