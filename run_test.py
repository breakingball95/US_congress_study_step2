#!/usr/bin/env python3
import subprocess
import sys

# 运行爬虫并传入'y'作为输入
process = subprocess.Popen(
    [sys.executable, 'scrape_china_statements.py'],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

stdout, _ = process.communicate(input='y\n', timeout=300)
print(stdout)
