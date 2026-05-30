#!/usr/bin/env python3
"""Test the providers command functionality."""

import sys
import os
from unittest.mock import Mock, patch

# Add current directory to Python path
sys.path.insert(0, '.')

def test_providers_command():
    """Test the providers CLI command."""
    print("Testing providers CLI command...")
    
    try:
        # Mock the provider factory to avoid dependency issues
        mock_factory = Mock()
        mock_factory.get_available_providers.return_value = ["bedrock", "gcp", "azure"]
        mock_factory.auto_detect_provider.return_value = None
        
        mock_provider = Mock()
        mock_provider.validate_config.return_value = False
        mock_factory.create_provider.return_value = mock_provider
        
        with patch('providers.ProviderFactory', mock_factory):
            # Import and test main module
            from main import app
            
            # Test that the app includes the providers command
            commands = [cmd.name for cmd in app.commands.values()]
            print(f"Available CLI commands: {commands}")
            assert 'providers' in commands
            
            print("✅ Providers command is available!")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    return True

def test_env_example():
    """Test that .env.example has been updated."""
    print("\nTesting .env.example updates...")
    
    try:
        with open('.env.example', 'r') as f:
            content = f.read()
        
        # Check for new provider sections
        required_sections = [
            'LLM_PROVIDER=bedrock',
            'GCP_PROJECT_ID=',
            'AZURE_OPENAI_ENDPOINT=',
        ]
        
        for section in required_sections:
            if section not in content:
                print(f"❌ Missing section: {section}")
                return False
            
        print("✅ .env.example updated correctly!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    return True

def test_pyproject_updates():
    """Test that pyproject.toml has been updated."""
    print("\nTesting pyproject.toml updates...")
    
    try:
        with open('pyproject.toml', 'r') as f:
            content = f.read()
        
        # Check for optional dependencies
        if 'optional-dependencies' not in content:
            print("❌ Missing [project.optional-dependencies] section")
            return False
            
        if 'google-cloud-aiplatform' not in content:
            print("❌ Missing GCP dependencies")
            return False
            
        if 'providers' not in content:
            print("❌ Missing providers in build targets")
            return False
            
        print("✅ pyproject.toml updated correctly!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = True
    success &= test_providers_command()
    success &= test_env_example()
    success &= test_pyproject_updates()
    
    if success:
        print("\n🎉 All validation tests passed!")
        sys.exit(0)
    else:
        print("\n💥 Some validation tests failed!")
        sys.exit(1)