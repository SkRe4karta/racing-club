"""Normalize pg_dump version comments and random psql restrict token only."""
import re
import sys

for line in sys.stdin:
    if line.startswith('-- Dumped from database version') or line.startswith('-- Dumped by pg_dump version'):
        continue
    line = re.sub(r'^(\\(?:un)?restrict) [A-Za-z0-9]+$', r'\1 LAB8SCHEMA', line.rstrip('\n'))
    print(line)
