"""
Quick test to verify Prometheus metrics endpoint works.

Run this after starting the server to verify metrics are exposed correctly.
"""

import requests

def test_metrics_endpoint():
    """Test that /metrics endpoint returns Prometheus metrics."""
    response = requests.get("http://localhost:8080/metrics")
    
    print(f"Status Code: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type')}")
    print("\n=== First 30 lines of metrics ===")
    
    lines = response.text.split('\n')[:30]
    for line in lines:
        print(line)
    
    # Verify expected metrics exist
    assert response.status_code == 200
    assert "text/plain" in response.headers.get('Content-Type', '')
    assert "mcp_http_requests_total" in response.text
    assert "mcp_http_request_duration_seconds" in response.text
    assert "mcp_tool_invocations_total" in response.text
    assert "mcp_tool_duration_seconds" in response.text
    
    print("\n✅ All expected metrics found in /metrics endpoint")

if __name__ == "__main__":
    try:
        test_metrics_endpoint()
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to http://localhost:8080")
        print("   Make sure the server is running: docker compose up")
    except AssertionError as e:
        print(f"❌ Assertion failed: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
