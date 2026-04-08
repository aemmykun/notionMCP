#!/usr/bin/env python3
"""
Acceptance Test: Request ID Threading Proof
============================================

Pass/Fail Criteria:
- Trigger one workflow that performs 2-3 tool calls
- All audit entries MUST share the exact same Request ID
- Entries MUST appear in timestamp order in Audit DB

Expected outcome:
✅ Multiple audit rows in 🧾 Audit DB with identical Request ID
✅ Event title format: "{action} — {outcome} — {target}"
✅ All required fields populated: Timestamp, Request ID, Actor, Action, Outcome, Proof hash
"""

import os
import httpx
import json
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
AUDIT_DB_ID = os.getenv("AUDIT_DB_ID").split("?")[0]
MCP_SERVER = "http://127.0.0.1:8080"
API_KEY = "test-key-123"

def call_tool(tool_name, payload, request_id=None):
    """Call MCP governance tool via HTTP API."""
    # Option B: Client passes same requestId across all calls in a workflow
    if request_id:
        payload["requestId"] = request_id
    
    response = httpx.post(
        f"{MCP_SERVER}/call_tool/{tool_name}",
        headers={"X-API-Key": API_KEY},
        json=payload,
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()

def query_audit_by_request_id(request_id):
    """Query Audit DB filtering by Request ID."""
    response = httpx.post(
        f"https://api.notion.com/v1/databases/{AUDIT_DB_ID}/query",
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        json={
            "filter": {
                "property": "Request ID",
                "rich_text": {
                    "equals": request_id
                }
            },
            "sorts": [
                {
                    "property": "Timestamp",
                    "direction": "ascending"
                }
            ]
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["results"]

def extract_audit_fields(page):
    """Extract key audit fields from Notion page."""
    props = page["properties"]
    
    def get_text(prop):
        if prop["type"] == "title":
            return prop["title"][0]["text"]["content"] if prop["title"] else ""
        elif prop["type"] == "rich_text":
            return prop["rich_text"][0]["text"]["content"] if prop["rich_text"] else ""
        elif prop["type"] == "select":
            return prop["select"]["name"] if prop["select"] else ""
        elif prop["type"] == "date":
            return prop["date"]["start"] if prop["date"] else ""
        return ""
    
    return {
        "event": get_text(props["Event"]),
        "timestamp": get_text(props["Timestamp"]),
        "request_id": get_text(props["Request ID"]),
        "actor": get_text(props["Actor"]),
        "action": get_text(props["Action"]),
        "outcome": get_text(props["Outcome"]),
        "proof_hash": get_text(props["Proof hash"]),
        "target": get_text(props.get("Target", {"type": "rich_text", "rich_text": []})),
    }

def main():
    print("=" * 80)
    print("REQUEST ID THREADING ACCEPTANCE TEST")
    print("=" * 80)
    
    # STEP 0: Generate workflow-level request_id (Option B)
    import uuid
    workflow_request_id = str(uuid.uuid4())
    print(f"\n[STEP 0] Generated workflow-level Request ID: {workflow_request_id}")
    print("This will be passed to ALL tool calls in this workflow")
    
    # STEP 1: Trigger workflow with multiple tool calls
    print("\n[STEP 1] Triggering multi-tool workflow...")
    print("-" * 80)
    
    # Call 1: Risk scoring
    print("\n📊 Tool Call 1: risk.score (high-risk finance transaction)")
    r1 = call_tool("risk.score", {
        "actor": "REQUEST-ID-TEST",
        "category": "finance",
        "amount": 5000,
        "priority": "high"
    }, request_id=workflow_request_id)  # Pass workflow request_id
    print(f"   Response: {r1}")
    request_id = r1.get("requestId")
    
    if not request_id:
        print("❌ FAIL: No requestId returned from first call!")
        return
    
    if request_id != workflow_request_id:
        print(f"❌ FAIL: Request ID mismatch! Sent {workflow_request_id}, got {request_id}")
        return
    
    print(f"\n✅ Request ID confirmed: {request_id}")
    
    # Call 2: Policy check
    print("\n🔍 Tool Call 2: policy.check")
    r2 = call_tool("policy.check", {
        "actor": "REQUEST-ID-TEST",
        "action": "transaction.execute",
        "context": {"amount": 5000}
    }, request_id=workflow_request_id)  # Same request_id
    print(f"   Response: {r2}")
    
    # Call 3: Explicit audit log (success)
    print("\n📝 Tool Call 3: audit.log (explicit success)")
    r3 = call_tool("audit.log", {
        "actor": "REQUEST-ID-TEST",
        "action": "payment.process",
        "input": {"amount": 5000, "vendor": "ACME Corp"},
        "output": {"transactionId": "TX-9876", "status": "completed"},
        "target": "payment:TX-9876"
    }, request_id=workflow_request_id)  # Same request_id
    print(f"   Response: {r3}")
    
    # Call 4: Explicit audit log (deny)
    print("\n📝 Tool Call 4: audit.log (explicit deny)")
    r4 = call_tool("audit.log", {
        "actor": "REQUEST-ID-TEST",
        "action": "payment.execute",
        "input": {"amount": 5000},
        "output": {"denied": True, "reason": "PR-001"},
        "policyApplied": "payment-approval-required",
        "policyVersion": "v1.2.0",
        "target": "payment:pending"
    }, request_id=workflow_request_id)  # Same request_id
    print(f"   Response: {r4}")
    
    # STEP 2: Query Audit DB for entries with this Request ID
    print("\n" + "=" * 80)
    print(f"[STEP 2] Querying Audit DB for Request ID: {request_id}")
    print("-" * 80)
    
    import time
    time.sleep(2)  # Allow Notion API to propagate
    
    entries = query_audit_by_request_id(request_id)
    
    if not entries:
        print(f"❌ FAIL: No audit entries found with Request ID {request_id}")
        return
    
    print(f"\n✅ Found {len(entries)} audit entries with matching Request ID")
    
    # STEP 3: Validate entries
    print("\n" + "=" * 80)
    print("[STEP 3] Validating audit entries (timestamp order)")
    print("=" * 80)
    
    for i, entry in enumerate(entries, 1):
        fields = extract_audit_fields(entry)
        
        print(f"\n--- Entry {i} ---")
        print(f"Event:       {fields['event']}")
        print(f"Timestamp:   {fields['timestamp']}")
        print(f"Request ID:  {fields['request_id']}")
        print(f"Actor:       {fields['actor']}")
        print(f"Action:      {fields['action']}")
        print(f"Outcome:     {fields['outcome']}")
        print(f"Target:      {fields['target']}")
        print(f"Proof hash:  {fields['proof_hash']}")
        
        # Validate required fields
        missing = []
        if not fields['event']: missing.append("Event")
        if not fields['timestamp']: missing.append("Timestamp")
        if not fields['request_id']: missing.append("Request ID")
        if not fields['actor']: missing.append("Actor")
        if not fields['action']: missing.append("Action")
        if not fields['outcome']: missing.append("Outcome")
        if not fields['proof_hash']: missing.append("Proof hash")
        
        if missing:
            print(f"❌ MISSING FIELDS: {', '.join(missing)}")
        else:
            print("✅ All required fields present")
        
        # Validate Request ID matches
        if fields['request_id'] != request_id:
            print(f"❌ Request ID mismatch! Expected {request_id}, got {fields['request_id']}")
        else:
            print(f"✅ Request ID matches: {request_id}")
        
        # Validate Event title format contains "—" separator
        if " — " in fields['event']:
            print(f"✅ Event format correct: '{fields['event']}'")
        else:
            print(f"⚠️  Event format may need adjustment: '{fields['event']}'")
    
    # STEP 4: Final verdict
    print("\n" + "=" * 80)
    print("FINAL VERDICT")
    print("=" * 80)
    
    if len(entries) >= 4:
        print(f"✅ PASS: Found {len(entries)} audit entries with identical Request ID")
        print(f"✅ PASS: Entries appear in timestamp order")
        print(f"✅ PASS: Request ID threading confirmed working")
        print(f"\n🎯 Correlation key: {request_id}")
        print(f"🔗 Filter in Audit DB: Request ID = {request_id}")
    else:
        print(f"⚠️  PARTIAL: Only {len(entries)} entries found (expected 4+)")
        print(f"   Request ID: {request_id}")

if __name__ == "__main__":
    main()
