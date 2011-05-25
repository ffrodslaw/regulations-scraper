#!/usr/bin/env python

from optparse import OptionParser
from regscrape_lib.util import get_db
import sys

# arguments
arg_parser = OptionParser()
arg_parser.add_option('-r', '--restart', action="store_true", dest="restart_scrape", default=False)
arg_parser.add_option("-c", "--continue", action="store_true", dest="continue_scrape", default=False)
arg_parser.add_option("-C", "--check", action="store_true", dest="check", default=False)

def run(options, args):
    from regscrape_lib.actors import MasterActor
    import time
    
    import settings
    
    db = get_db()
    if settings.MODE == 'search' and (not options.continue_scrape) and (not options.restart_scrape) and len(db.collection_names()) > 0:
        print 'This database already contains data; please run with either --restart or --continue to specify what you want to do with it.'
        sys.exit()
        
    
    if settings.BROWSER['driver'] == 'Chrome':
        from regscrape_lib.monkey import patch_selenium_chrome
        patch_selenium_chrome()
    
    if settings.MODE == 'search':
        settings.CLEAR_FIRST = not options.continue_scrape
    else:
        settings.CLEAR_FIRST = False
    
    settings.CHECK_BEFORE_SCRAPE = options.check
    
    master = MasterActor.start(settings.INSTANCES)
    master.send_one_way({'command': 'scrape', 'max': settings.MAX_RECORDS})
    while True:
        time.sleep(60)
        master.send_one_way({'command': 'tick'})
