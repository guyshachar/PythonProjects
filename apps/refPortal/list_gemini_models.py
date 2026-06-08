#!/usr/bin/env python3
"""
Quick script to list available Gemini models
"""

import os
import sys
import google.generativeai as genai

api_key = os.getenv('GEMINI_API_KEY') or sys.argv[1] if len(sys.argv) > 1 else None

if not api_key:
    print("Error: Please provide API key as argument or set GEMINI_API_KEY environment variable")
    print("Usage: python list_gemini_models.py YOUR_API_KEY")
    sys.exit(1)

try:
    genai.configure(api_key=api_key)
    
    print("Available Gemini Models:")
    print("=" * 60)
    
    models = list(genai.list_models())
    
    for model in models:
        model_id = model.name.replace('models/', '')
        methods = getattr(model, 'supported_generation_methods', [])
        
        if 'generateContent' in methods:
            print(f"✓ {model_id}")
            print(f"  Methods: {', '.join(methods)}")
            if hasattr(model, 'display_name'):
                print(f"  Display Name: {model.display_name}")
            print()
    
    print("\nRecommended models for CV tailoring:")
    print("  - gemini-pro (stable, widely available)")
    print("  - gemini-1.5-pro-latest (latest, best quality)")
    print("  - gemini-1.5-flash-latest (faster, good quality)")
    
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)





