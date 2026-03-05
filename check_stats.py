#!/usr/bin/env python3
import csv

with open('house_representatives_social_media.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    results = list(reader)
    
total = len(results)
x_count = sum(1 for r in results if r.get('X'))
fb_count = sum(1 for r in results if r.get('Facebook'))
both_count = sum(1 for r in results if r.get('X') and r.get('Facebook'))

print(f'总爬取数量: {total}')
print(f'有X链接: {x_count} ({x_count/total*100:.1f}%)')
print(f'有Facebook链接: {fb_count} ({fb_count/total*100:.1f}%)')
print(f'两者都有: {both_count} ({both_count/total*100:.1f}%)')
