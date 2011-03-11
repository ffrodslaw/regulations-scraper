from scrapelib.util import get_elements
from scrapelib.document import scrape_document

def scrape_listing(browser, url=None, visit_first=True):
    if visit_first:
        browser.get(url)
    
    num_links = len(get_elements(browser, '.Gsqk2cNV table.x-grid3-row-table tr div.gridCell a'))
    for num in range(num_links):
        link = get_elements(browser, '.Gsqk2cNV table.x-grid3-row-table tr div.gridCell a')[num]
        href = link.get_attribute('href')
        id = href.split('=')[1]
        
        link.click()
        
        print scrape_document(browser, id, False)
        
        browser.back()