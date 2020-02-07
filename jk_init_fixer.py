#!/usr/bin/env python

import glob
import os
import re
import sys


infile = '/etc/jailkit/jk_init.ini'
outfile = infile + '.new'

dirs = ['/lib', '/lib64', '/usr/lib', '/usr/lib64']
dirs.extend(glob.glob('/lib/*-gnu'))
dirs.extend(glob.glob('/usr/lib/*-gnu'))

line_re = re.compile(r'^(\s*paths\s*=\s*)(.*)')
split_re = re.compile(r'\s*,\s*')
suffix_re = re.compile(r'(\.so)\..*')

with open(infile, 'r') as inf, open(outfile, 'w') as outf:
    outf.write('# FIXED\n')
    for line in inf:
        line_match = line_re.match(line)
        if line_match is None:
            outf.write(line)
            continue
        paths = split_re.split(line_match.group(2))
        matches = []
        for path in paths:
            if '/lib' not in path or '.so' not in path:
                matches.append(path)
                continue
            basename = os.path.basename(path)
            basename = suffix_re.sub(r'\1.*', basename)
            for d in dirs:
                pattern = os.path.join(d, basename)
                if glob.glob(pattern):
                    if pattern not in matches:
                        matches.append(pattern)
        outf.write(line_match.group(1) + ', '.join(matches) + '\n')

if not os.path.exists(infile + '.orig'):
    os.rename(infile, infile + '.orig')

os.rename(outfile, infile)
