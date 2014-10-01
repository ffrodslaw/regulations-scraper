#!/usr/bin/env python

from bson.code import Code
from pymongo.errors import OperationFailure, InvalidDocument
import subprocess, os, urlparse, json
from gevent import Timeout
from regs_models import *
from exceptions import ExtractionFailed, ChildTimeout
import os
import re
import cStringIO
import time
import itertools
import sys
import regs_common
import operator
import zlib
import settings

def find_views(**params):
    db = Doc._get_db()
    
    # allow for using a pre-filter to speed up execution
    kwargs = {}
    query = {}
    if 'query' in params:
        query = params['query']
        del params['query']
    
    # create the actual map function
    conditions = dict([('views.%s' % item[0], item[1]) for item in params.items()])
    conditions.update(query)
    
    results = itertools.chain.from_iterable(
        itertools.imap(
            lambda doc: [{'view': View._from_son(view), 'doc': doc['_id']} for view in doc['views'] if all(item[0] in view and view[item[0]] == item[1] for item in params.items())],
            db.docs.find(conditions)
        )
    )
    
    return results

def find_attachment_views(**params):
    db = Doc._get_db()

    # allow for using a pre-filter to speed up execution
    kwargs = {}
    query = {}
    if 'query' in params:
        query = params['query']
        del params['query']

    # create the actual map function
    conditions = dict([('attachments.views.%s' % item[0], item[1]) for item in params.items()])
    conditions.update(query)

    results = itertools.chain.from_iterable(
        itertools.imap(
            lambda doc: reduce(operator.add, [
                [
                    {'view': View._from_son(view), 'doc': doc['_id'], 'attachment': attachment['object_id']}
                    for view in attachment['views'] if all(item[0] in view and view[item[0]] == item[1] for item in params.items())
                ] for attachment in doc['attachments']
            ] if 'attachments' in doc else [], []),
            db.docs.find(conditions)
        )
    )

    return results

def update_view(doc, view):    
    # use db object from thread pool
    db = Doc._get_db()
    
    # can't figure out a way to do this atomically because of bug SERVER-1050
    # remove the old version of the view
    db.docs.update({
        '_id': doc
    },
    {
        '$pull': {"views": {"url": view.url}}
    }, safe=True)

    # add the new one back
    db.docs.update({
        '_id': doc
    },
    {
        '$push': {"views": view.to_mongo()}
    }, safe=True)
    
    # return it to the pool
    del db

def update_attachment_view(doc, attachment, view):    
    db = Doc._get_db()
    
    # two-stage push/pull as above
    db.docs.update({
        '_id': doc,
        'attachments.object_id': attachment
    },
    {
        '$pull': {'attachments.$.views': {'url': view.url}}
    }, safe=True)

    db.docs.update({
        '_id': doc,
        'attachments.object_id': attachment
    },
    {
        '$push': {'attachments.$.views': view.to_mongo()}
    }, safe=True)

    
    del db


# the following is from http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python
def which(program):
    import os
    def is_exe(fpath):
        return os.path.exists(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None

# the following is from http://stackoverflow.com/questions/92438/stripping-non-printable-characters-from-a-string-in-python
import unicodedata, re

control_chars = ''.join(map(unichr, range(0,10) + range(11,13) + range(14,32) + range(127,160)))

control_char_re = re.compile('[%s]' % re.escape(control_chars))

def remove_control_chars(s):
    return control_char_re.sub('', s)

# extractor
POPEN = subprocess.Popen
_nbsp = re.compile('(&nbsp;?|&#160;?|&#xa0;?)')
def binary_extractor(binary, error=None, append=[], output_type="text"):
    if not type(binary) == list:
        binary = [binary]
    def extractor(filename):
        interpreter = POPEN(binary + [filename] + append, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        timeout = Timeout(getattr(settings, 'EXTRACTION_TIMEOUT', 120), ChildTimeout)
        timeout.start()
        try:
            output, run_error = interpreter.communicate('')
            timeout.cancel()
        except ChildTimeout:
            print 'killing %s' % filename
            interpreter.kill()
            raise
        
        if (output_type == 'text' and not output.strip()) or (output_type == 'html' and html_is_empty(output)) or (error and (error in output or error in run_error)):
            raise ExtractionFailed()
        elif output_type == 'html':
            # strip non-breaking spaces
            return _nbsp.sub(' ', output)
        else:
            return output
    
    extractor.__str__ = lambda: binary[0]
    extractor.output_type = output_type
    
    return extractor

def script_extractor(script, error=None, output_type="text"):
    script_path = os.path.join(os.path.dirname(os.path.abspath(regs_common.__file__)), 'scripts', script)
    
    extractor = binary_extractor([sys.executable, script_path], error=error, output_type=output_type)
    extractor.__str__ = lambda: script
    
    return extractor

_tag_stripper = re.compile(r'<[^>]*?>')
def strip_tags(text):
    return _tag_stripper.sub('', text)

_body_finder = re.compile(r"<body[^>]*>(.*)</body>", re.I | re.DOTALL)
_outline_finder = re.compile(r'<a name="outline"></a>\s*<h1>Document Outline</h1>\s*<ul>.*</ul>', re.I | re.DOTALL)
def html_is_empty(text):
    # grab the body
    body = _body_finder.findall(text)
    if not body:
        return True
    
    # explicitly strip out pdftohtml's document outlines
    without_outline = _outline_finder.sub("", body[0])
    
    body_text = strip_tags(without_outline).strip()
    if not body_text:
        return True
    
    return False

def ocr_scrub(text):
    lines = re.split(r'\n', text)
    garbage = re.compile(r'[^a-zA-Z\s]')
    
    def is_real_line(word):
        letter_length = len(garbage.sub('', word))
        return letter_length and len(word) and letter_length/float(len(word)) >= 0.5
    
    filtered_lines = [line.strip() for line in lines if line and is_real_line(line)]
    filtered_text = '\n'.join(filtered_lines)
    
    if len(filtered_text) / float(len(text)) < 0.5:
        raise ExtractionFailed('This is does not appear to be text.')
    
    return filtered_text

def pdf_ocr(filename):
    basename = os.path.basename(filename).split('.')[0]
    working = '/tmp/%s' % basename
    if not os.path.exists(working):
        os.mkdir(working)
    os.chdir(working)
    
    def cleanup():
        if working and working != '/tmp/':
            os.chdir('..')
            subprocess.Popen(['rm', '-rf', working], stdout=subprocess.PIPE).communicate()
    
    extractor = subprocess.Popen(['pdfimages', filename, basename], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    extractor_output, extractor_error = extractor.communicate()
    if extractor_error:
        cleanup()
        raise ExtractionFailed("Failed to extract image data from PDF.")
    
    pnm_match = re.compile(r"[a-zA-Z0-9]+-[0-9]+\.p.m")
    pnms = [file for file in os.listdir(working) if pnm_match.match(file)]
    if not pnms:
        cleanup()
        raise ExtractionFailed("No images found in PDF.")
    
    converter = subprocess.Popen(['gm', 'mogrify', '-format', 'tiff', '-type', 'Grayscale'] + pnms, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    converter_output, converter_error = converter.communicate()
    if converter_error:
        cleanup()
        raise ExtractionFailed("Failed to convert images to tiff.")
    
    tiff_match = re.compile(r"[a-zA-Z0-9]+-[0-9]+\.tiff")
    tiffs = [file for file in os.listdir(working) if tiff_match.match(file)]
    if not tiffs:
        cleanup()
        raise ExtractionFailed("Converted tiffs not found.")
    
    out = cStringIO.StringIO()
    for tiff in tiffs:
        tiff_base = tiff.split('.')[0]
        ocr = subprocess.Popen(['tesseract', tiff, tiff_base], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ocr_output, ocr_error = ocr.communicate()
        
    txt_match = re.compile(r"[a-zA-Z0-9]+-[0-9]+\.txt")
    txts = [file for file in os.listdir(working) if txt_match.match(file)]
    if not txts:
        cleanup()
        raise ExctractionFailed("OCR failed to find any text.")
    
    for txt in txts:
        ocr_file = open(txt, 'r')
        out.write(ocr_file.read())
        out.write('\n')
    
    try:
        return_data =  ocr_scrub(out.getvalue())
    except ExtractionFailed:
        cleanup()
        raise
    
    cleanup()
    return return_data
pdf_ocr.__str__ = lambda: 'tesseract'
pdf_ocr.ocr = True
