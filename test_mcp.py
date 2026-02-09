"""
Test script for GitHub MCP via HTTP endpoint
"""
import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

# Get token from environment - NEVER hardcode tokens!
GITHUB_TOKEN = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")

async def test_mcp_direct():
    """Test GitHub MCP endpoint directly with httpx"""
    if not GITHUB_TOKEN:
        print("❌ GITHUB_PERSONAL_ACCESS_TOKEN not set")
        return False
    
    print(f"🔑 Token found: {GITHUB_TOKEN[:15]}...")
    
    # Test 1: Check if endpoint is reachable
    print("\n📡 Test 1: Checking MCP endpoint...")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://api.githubcopilot.com/mcp/",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
                timeout=10.0
            )
            print(f"   Status: {response.status_code}")
            print(f"   Headers: {dict(response.headers)}")
            if response.text:
                print(f"   Body: {response.text[:500]}")
        except Exception as e:
            print(f"   Error: {e}")
    
    # Test 2: Try MCP initialize via POST
    print("\n📡 Test 2: Trying MCP initialize...")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.githubcopilot.com/mcp/",
                headers={
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1.0"}
                    }
                },
                timeout=10.0
            )
            print(f"   Status: {response.status_code}")
            print(f"   Body: {response.text[:1000]}")
        except Exception as e:
            print(f"   Error: {e}")
    
    return True

if __name__ == "__main__":
    result = asyncio.run(test_mcp_direct())
    exit(0 if result else 1)
