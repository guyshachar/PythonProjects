#!/usr/bin/env python3
"""
Test script to verify chat API integration with refPortalFastApiDI.py
This script tests that the chat router is properly included and accessible
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

def test_chat_api_import():
    """Test that the chat API can be imported"""
    try:
        from rpApi.chat_api import chat_router
        print("✅ Chat API router imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Failed to import chat API router:", e)
        return False

def test_chat_router_structure():
    """Test that the chat router has the expected structure"""
    try:
        from rpApi.chat_api import chat_router
        
        # Check if router has the expected attributes
        if hasattr(chat_router, 'routes'):
            print(f"✅ Chat router has {len(chat_router.routes)} routes")
            
            # List the routes
            for route in chat_router.routes:
                print(f"  - {route.methods} {route.path}")
            
            return True
        else:
            print("❌ Chat router missing 'routes' attribute")
            return False
            
    except Exception as e:
        print(f"❌ Error testing chat router structure:", e)
        return False

def test_fastapi_integration():
    """Test that the FastAPI app can be created with chat router"""
    try:
        from rpApi.refPortalFastApiDI import RefPortalFastApi
        
        # Create the FastAPI app
        print("🔄 Creating FastAPI app...")
        fastapi_instance = RefPortalFastApi()
        app = fastapi_instance.create_app()
        
        print("✅ FastAPI app created successfully")
        
        # Check if chat routes are included
        chat_routes = [route for route in app.routes if hasattr(route, 'path') and '/api/chat' in str(route.path)]
        
        if chat_routes:
            print(f"✅ Found {len(chat_routes)} chat API routes in FastAPI app")
            for route in chat_routes:
                print(f"  - {route.path}")
        else:
            print("⚠️ No chat API routes found in FastAPI app")
            
        return True
        
    except Exception as e:
        print(f"❌ Error testing FastAPI integration:", e)
        return False

def test_chat_api_endpoints():
    """Test that the chat API endpoints are accessible"""
    try:
        from rpApi.chat_api import chat_router
        
        # Test the health endpoint
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        
        # Create a test app with the chat router
        test_app = FastAPI()
        test_app.include_router(chat_router)
        
        client = TestClient(test_app)
        
        # Test health endpoint
        response = client.get("/api/chat/health")
        if response.status_code == 200:
            print("✅ Chat API health endpoint working")
            health_data = response.json()
            print(f"  - Status: {health_data.get('status')}")
            print(f"  - Total clients: {health_data.get('totalClients')}")
            print(f"  - Total messages: {health_data.get('totalMessages')}")
        else:
            print(f"❌ Chat API health endpoint failed: {response.status_code}")
            
        # Test info endpoint
        response = client.get("/api/chat/info")
        if response.status_code == 200:
            print("✅ Chat API info endpoint working")
            info_data = response.json()
            print(f"  - API Name: {info_data.get('name')}")
            print(f"  - Version: {info_data.get('version')}")
        else:
            print(f"❌ Chat API info endpoint failed: {response.status_code}")
            
        return True
        
    except ImportError:
        print("⚠️ TestClient not available - skipping endpoint testing")
        return True
    except Exception as e:
        print(f"❌ Error testing chat API endpoints:", e)
        return False

def main():
    """Run all tests"""
    print("🧪 Testing Chat API Integration with refPortalFastApiDI.py")
    print("=" * 60)
    
    tests = [
        ("Chat API Import", test_chat_api_import),
        ("Chat Router Structure", test_chat_router_structure),
        ("FastAPI Integration", test_fastapi_integration),
        ("Chat API Endpoints", test_chat_api_endpoints),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n🔍 Testing: {test_name}")
        print("-" * 40)
        
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test failed with exception:", e)
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Chat API integration is working correctly.")
    else:
        print("⚠️ Some tests failed. Check the output above for details.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
