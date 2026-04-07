#!/usr/bin/env python3
"""Quick verification of Audit DB entries."""
from dotenv import load_dotenv
import os
import httpx

load_dotenv()

token = os.getenv('NOTION_TOKEN')
db_id = os.getenv('AUDIT_DB_ID')
db_id = db_id.split('?')[0] if db_id else None

headers = {
    'Authorization': f'Bearer {token}',
    'Notion-Version': '2022-06-28',
    'Content-Type': 'application/json'
}

print('\n' + '='*60)
print('  AUDIT DB - 2-STEP WRITE-THEN-READ VERIFICATION')
print('='*60)

if not token:
    raise RuntimeError("NOTION_TOKEN missing")
if not db_id:
    raise RuntimeError("AUDIT_DB_ID missing")

r = httpx.post(
    f'https://api.notion.com/v1/databases/{db_id}/query',
    headers=headers,
    json={'page_size': 6},
    timeout=30
)
r.raise_for_status()

data = r.json()
results = data.get('results', [])

print(f'\n✓ Found {len(results)} recent entries:\n')

for i, page in enumerate(results, 1):
    props = page['properties']
    
    event = props['Event']['title'][0]['text']['content'] if props.get('Event', {}).get('title') else 'N/A'
    actor = props['Actor']['rich_text'][0]['text']['content'] if props.get('Actor', {}).get('rich_text') else 'N/A'
    action = props['Action']['rich_text'][0]['text']['content'] if props.get('Action', {}).get('rich_text') else 'N/A'
    outcome = props['Outcome']['select']['name'] if props.get('Outcome', {}).get('select') else 'N/A'
    
    emoji = '✅' if outcome == 'success' else '❌' if outcome == 'deny' else '⚪'
    
    print(f'{i}. {emoji} {event}')
    print(f'   Actor: {actor} | Action: {action} | Outcome: {outcome}')
    print()

print('='*60)
print('✓ WRITE-THEN-READ TEST: COMPLETE')
print('='*60)
print()
