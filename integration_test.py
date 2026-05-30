"""Simple integration test to verify provider system works."""

# Test the main imports and basic functionality
def test_imports():
    """Test that all modules can be imported."""
    try:
        # Test provider imports
        print("Testing provider imports...")
        from providers.base import LLMProvider, ModelConfig
        from providers.bedrock import BedrockProvider
        from providers.gcp import GCPProvider
        from providers.azure import AzureProvider
        from providers.factory import ProviderFactory
        from providers import ProviderFactory as MainFactory
        
        print("✓ All provider modules imported successfully")
        
        # Test basic functionality
        print("\nTesting basic functionality...")
        
        # Create model config
        config = ModelConfig(model_id="test", max_tokens=1000)
        print(f"✓ ModelConfig created: {config.model_id}")
        
        # Get available providers
        providers = ProviderFactory.get_available_providers()
        print(f"✓ Available providers: {providers}")
        
        # Test provider creation (this might fail due to missing deps, that's ok)
        try:
            bedrock = ProviderFactory.create_provider("bedrock")
            print(f"✓ Bedrock provider created: {bedrock.provider_name}")
        except Exception as e:
            print(f"⚠ Bedrock creation failed (expected): {e}")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def test_main_integration():
    """Test main.py integration."""
    try:
        print("\nTesting main.py integration...")
        
        # Import main and check for new command
        import main
        
        # Check if providers command exists
        has_providers_cmd = any(cmd.name == 'providers' for cmd in main.app.commands.values())
        if has_providers_cmd:
            print("✓ Providers command found in main.py")
        else:
            print("❌ Providers command not found in main.py")
            return False
        
        # Check if --provider option exists in run command
        run_cmd = next((cmd for cmd in main.app.commands.values() if cmd.name == 'run'), None)
        if run_cmd:
            # Check if provider parameter exists in the function signature
            import inspect
            sig = inspect.signature(run_cmd.callback)
            has_provider_param = 'provider' in sig.parameters
            if has_provider_param:
                print("✓ --provider option found in run command")
            else:
                print("❌ --provider option not found in run command")
                return False
        
        return True
        
    except Exception as e:
        print(f"❌ Main integration test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("Running provider system integration tests...\n")
    
    success = True
    success &= test_imports()
    success &= test_main_integration()
    
    if success:
        print("\n🎉 All integration tests passed!")
        print("\nProvider system successfully integrated!")
        print("\nNext steps:")
        print("1. Install optional dependencies: pip install -e '[gcp]'")
        print("2. Configure your preferred provider in .env")
        print("3. Run: python main.py providers")
    else:
        print("\n💥 Some integration tests failed!")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())