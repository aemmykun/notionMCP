#!/usr/bin/env python3
"""Query and display all Notion databases."""
import os
from dotenv import load_dotenv
import httpx

load_dotenv()

NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_VERSION = "2022-06-28"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

def clean_db_id(value):
    return value.split('?')[0] if value else None

# Database IDs
GOVERNANCE_DB_ID = clean_db_id(os.getenv('GOVERNANCE_DB_ID'))
AUDIT_DB_ID = clean_db_id(os.getenv('AUDIT_DB_ID'))
WORKFLOW_DB_ID = clean_db_id(os.getenv('WORKFLOW_DB_ID'))
APPROVAL_DB_ID = clean_db_id(os.getenv('APPROVAL_DB_ID'))

def query_database(database_id, page_size=10):
    """Query a Notion database using direct HTTP API."""
    if not NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN missing")
    if not database_id:
        raise ValueError("Database ID missing")
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    response = httpx.post(url, headers=headers, json={"page_size": page_size}, timeout=30.0)
    response.raise_for_status()
    return response.json()

def get_prop_value(props, key):
    """Extract value from Notion property."""
    try:
        prop = props.get(key, {})
        prop_type = prop.get('type')
        
        if prop_type == 'title':
            return prop['title'][0]['text']['content'] if prop.get('title') else ''
        elif prop_type == 'rich_text':
            return prop['rich_text'][0]['text']['content'] if prop.get('rich_text') else ''
        elif prop_type == 'select':
            return prop['select']['name'] if prop.get('select') else ''
        elif prop_type == 'number':
            return str(prop.get('number', '')) if prop.get('number') is not None else ''
        elif prop_type == 'date':
            date_obj = prop.get('date', {})
            return date_obj.get('start', '') if date_obj else ''
    except:
        return ''
    return ''

def print_table_header(title):
    print('\n' + '='*80)
    print(f'  {title}')
    print('='*80)

def print_row(label, value, indent=2):
    print(' ' * indent + f'{label}: {value}')

# Query Governance Database
print_table_header('GOVERNANCE DATABASE (Policies)')
try:
    gov_results = query_database(GOVERNANCE_DB_ID)
    if gov_results.get('results'):
        count = 0
        for page in gov_results['results']:
            count += 1
            props = page['properties']
            print(f'\n  [{count}] {get_prop_value(props, "Name")}')
            print_row('Category', get_prop_value(props, 'Category'), 6)
            print_row('Status', get_prop_value(props, 'Status'), 6)
        print(f'\n  Total entries: {len(gov_results["results"])}')
    else:
        print('  No entries found')
except Exception as e:
    import traceback
    print(f'  Error: {e}')
    print(f'  Traceback: {traceback.format_exc()}')

# Query Audit Database
print_table_header('AUDIT DATABASE (Audit Log)')
try:
    audit_results = query_database(AUDIT_DB_ID, page_size=15)
    if audit_results.get('results'):
        count = 0
        for page in audit_results['results']:
            count += 1
            props = page['properties']
            event = get_prop_value(props, 'Event')
            outcome = get_prop_value(props, 'Outcome')
            actor = get_prop_value(props, 'Actor')
            
            outcome_emoji = '✅' if outcome == 'success' else '❌' if outcome == 'deny' else '⚪'
            print(f'\n  [{count}] {outcome_emoji} {event}')
            print_row('Actor', actor, 6)
            print_row('Action', get_prop_value(props, 'Action'), 6)
            print_row('Outcome', outcome, 6)
            
            reason = get_prop_value(props, 'Reason codes')
            if reason:
                print_row('Reason', reason, 6)
            
            proof = get_prop_value(props, 'Proof hash')
            if proof:
                print_row('Proof Hash', proof[:32] + '...' if len(proof) > 32 else proof, 6)
        
        print(f'\n  Total entries: {len(audit_results["results"])}')
    else:
        print('  No entries found')
except Exception as e:
    import traceback
    print(f'  Error: {e}')
    print(f'  Traceback: {traceback.format_exc()}')

# Query Workflow Database
print_table_header('WORKFLOW DATABASE (Tasks)')
try:
    workflow_results = query_database(WORKFLOW_DB_ID)
    if workflow_results.get('results'):
        count = 0
        for page in workflow_results['results']:
            count += 1
            props = page['properties']
            print(f'\n  [{count}] {get_prop_value(props, "Name")}')
            print_row('Type', get_prop_value(props, 'Type'), 6)
            print_row('Status', get_prop_value(props, 'Status'), 6)
            print_row('Priority', get_prop_value(props, 'Priority'), 6)
        print(f'\n  Total entries: {len(workflow_results["results"])}')
    else:
        print('  No entries found')
except Exception as e:
    import traceback
    print(f'  Error: {e}')
    print(f'  Traceback: {traceback.format_exc()}')

# Query Approval Database
print_table_header('APPROVAL DATABASE (Approval Requests)')
try:
    approval_results = query_database(APPROVAL_DB_ID)
    if approval_results.get('results'):
        count = 0
        for page in approval_results['results']:
            count += 1
            props = page['properties']
            print(f'\n  [{count}] {get_prop_value(props, "Name")}')
            print_row('Requester', get_prop_value(props, 'Requester'), 6)
            print_row('Status', get_prop_value(props, 'Status'), 6)
            print_row('Risk', get_prop_value(props, 'Risk'), 6)
        print(f'\n  Total entries: {len(approval_results["results"])}')
    else:
        print('  No entries found')
except Exception as e:
    import traceback
    print(f'  Error: {e}')
    print(f'  Traceback: {traceback.format_exc()}')

print('\n' + '='*80 + '\n')
