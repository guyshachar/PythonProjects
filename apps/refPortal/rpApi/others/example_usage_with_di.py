#!/usr/bin/env python3.12
"""
Example usage of RefPortalImplementationFastApi with dependency injection and LLM enhancer
"""

import os
import sys
from pathlib import Path

# Add shared modules to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.appContainer import AppContainer
from shared.configurationDI import configDI
from rpApi.refPortalImplementationFastApiDI import create_ref_portal_implementation_from_container

def main():
    """Example of how to create RefPortalImplementationFastApi with LLM enhancer using DI"""
    
    # Create and configure the dependency injection container
    container = AppContainer()
    container.config.from_dict(configDI)
    container.init_resources()
    
    try:
        # Create the RefPortalImplementationFastApi instance with all dependencies injected
        ref_portal_api = create_ref_portal_implementation_from_container(container)
        
        # Now you can use the API with LLM enhancer available
        if ref_portal_api.llm_enhancer:
            print("✅ LLM enhancer successfully injected and available")
        else:
            print("⚠️  LLM enhancer not available (check configuration)")
        
        # Example usage
        print(f"API initialized with logger: {ref_portal_api.logger}")
        print(f"Database client: {ref_portal_api.dbClient}")
        print(f"Messaging service: {ref_portal_api.messagingService}")
        
    except Exception as e:
        print(f"❌ Error creating RefPortalImplementationFastApi:", e)
    finally:
        # Clean up resources
        container.shutdown_resources()

if __name__ == "__main__":
    main()
