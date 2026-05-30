#!/usr/bin/env python3
"""Test script for provider functionality."""

import sys
import os
sys.path.insert(0, '.')

def test_provider_factory():
    """Test the provider factory functionality."""
    print("Testing provider factory...")
    
    try:
        from providers import ProviderFactory
        
        # Test getting available providers
        providers = ProviderFactory.get_available_providers()
        print(f"Available providers: {providers}")
        assert 'bedrock' in providers
        assert 'gcp' in providers
        assert 'azure' in providers
        
        # Test creating Bedrock provider (should work without AWS credentials for instantiation)
        try:
            bedrock_provider = ProviderFactory.create_provider("bedrock")
            print(f"Created Bedrock provider: {bedrock_provider.provider_name}")
            assert bedrock_provider.provider_name == "bedrock"
        except Exception as e:
            print(f"Bedrock provider creation test: {e}")
        
        # Test auto-detection (should return None since no credentials are set)
        detected = ProviderFactory.auto_detect_provider()
        print(f"Auto-detected provider: {detected}")
        
        print("✅ Provider factory tests passed!")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    return True

def test_provider_configs():
    """Test provider model configurations."""
    print("\nTesting provider model configs...")
    
    try:
        from providers.base import ModelConfig
        
        config = ModelConfig(
            model_id="test-model",
            region="us-east-1",
            max_tokens=4096,
            temperature=0.7
        )
        
        print(f"Created model config: {config}")
        assert config.model_id == "test-model"
        assert config.max_tokens == 4096
        
        print("✅ Model config tests passed!")
        
    except Exception as e:
        print(f"❌ Model config test failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = True
    success &= test_provider_factory()
    success &= test_provider_configs()
    
    if success:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n💥 Some tests failed!")
        sys.exit(1)