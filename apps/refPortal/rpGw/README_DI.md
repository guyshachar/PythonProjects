# RefPortalServiceDI - Dependency Injection Implementation

This document describes how to use the new `RefPortalServiceDI` class that implements dependency injection using the `shared.appContainer`.

## Overview

The `RefPortalServiceDI` class is a refactored version of the original `RefPortalService` that uses dependency injection to manage all its dependencies. This provides better testability, maintainability, and separation of concerns.

## Key Features

- **Dependency Injection**: All dependencies are injected from the `shared.appContainer`
- **Configurable**: Easy to configure with different settings
- **Testable**: Easy to mock dependencies for testing
- **Consistent**: Uses the same container as other parts of the application

## Usage

### Basic Usage

```python
from rpService.refPortalServiceDI import RefPortalServiceDI

# Create service with default container
service = RefPortalServiceDI()
await service.start()
```

### With Custom Container

```python
from rpService.refPortalServiceDI import RefPortalServiceDI
from shared.appContainer import AppContainer

# Create custom container
container = AppContainer()
container.config.from_dict({
    "env": "production",
    "db": {"type": "dynamodb"},
    "aws": {
        "region": "us-east-1",
        "dynamodb": {"endpointUrl": "https://dynamodb.us-east-1.amazonaws.com"}
    }
})

# Create service with custom container
service = RefPortalServiceDI(container)
await service.start()
```

### Using Factory Function

```python
from rpService.refPortalServiceDI import create_ref_portal_service_di

# Create service using factory function
service = create_ref_portal_service_di()
await service.start()
```

## Injected Dependencies

The following dependencies are automatically injected from the container:

- `logger`: Application logger
- `db_client`: Database client (Redis or DynamoDB)
- `messaging_service`: Messaging service
- `handle_users`: User management handlers
- `handle_tournaments`: Tournament management handlers
- `handle_referee_data`: Referee data handlers
- `referee_process_service`: Referee process service

## Configuration

The service uses environment variables for configuration:

- `app_env`: Application environment
- `db`: Database type ('redis' or 'dynamodb')
- `redisHost`, `redisPort`, `redisDb`: Redis configuration
- `awsRegion`, `dynamoDbEndpointUrl`: AWS configuration
- `generateReports`: Whether to generate reports
- `mainInstance`: Whether this is the main instance
- `loadInterval`: Processing interval in milliseconds
- `refereesPerRun`: Number of referees to process per batch
- `enableCronjobs`: Enables/disables the internal cronjob scheduler
- `cronjobPollIntervalSeconds`: How often the scheduler checks due jobs
- `cronjobConfigFile`: Optional path to cronjobs JSON file (default: `config/cronjobs.json`)

Cronjob entries support:
- `type`: `api` or `function`
- `endpoint`: Required for `type=api` (e.g. `/api/health` or full URL)
- `function`: Required for `type=function` (supported: `refreshLeaguesTables`, `refreshTournamentGames`, `startRefereeProcessing`)
- `intervalSeconds` / `intervalMinutes` / `intervalHours`
- `enabled`, `instanceTarget` (`mainOnly` | `all` | `odd` | `even`), `runOnStartup`

## Testing

The DI implementation makes testing much easier:

```python
import pytest
from unittest.mock import Mock
from rpService.refPortalServiceDI import RefPortalServiceDI

def test_ref_portal_service_di():
    # Create mock container
    mock_container = Mock()
    mock_container.logger.return_value = Mock()
    mock_container.db_client.return_value = Mock()
    mock_container.messaging_service.return_value = Mock()
    mock_container.handle_users.return_value = Mock()
    mock_container.handle_tournaments.return_value = Mock()
    mock_container.handle_referee_data.return_value = Mock()
    mock_container.referee_process_service.return_value = Mock()
    
    # Create service with mock container
    service = RefPortalServiceDI(mock_container)
    
    # Test that dependencies are properly injected
    assert service.logger is not None
    assert service.db_client is not None
    assert service.messaging_service is not None
```

## Migration from Original Service

To migrate from the original `RefPortalService` to `RefPortalServiceDI`:

1. **Import Change**:
   ```python
   # Old
   from rpService.refPortalService import RefPortalService
   
   # New
   from rpService.refPortalServiceDI import RefPortalServiceDI
   ```

2. **Instantiation**:
   ```python
   # Old
   service = RefPortalService()
   
   # New
   service = RefPortalServiceDI()
   ```

3. **Method Names**: Most method names have been updated to follow Python naming conventions:
   - `loadMetadata()` → `load_metadata()`
   - `updateRefereeAddress()` → `update_referee_address()`
   - `shouldLoadRefereesFile()` → `should_load_referees_file()`
   - `readRefereeDetails()` → `read_referee_details()`
   - `writeRefereeDetails()` → `write_referee_details()`
   - `resetProgress()` → `reset_progress()`
   - `simulateDynamicProgress()` → `simulate_dynamic_progress()`

## Benefits

1. **Testability**: Easy to mock dependencies for unit testing
2. **Maintainability**: Clear separation of concerns
3. **Flexibility**: Easy to swap implementations
4. **Consistency**: Uses the same DI container as the rest of the application
5. **Configuration**: Centralized configuration management

## Running the Service

```bash
# Run the service directly
python rpService/refPortalServiceDI.py

# Or import and use in your application
from rpService.refPortalServiceDI import RefPortalServiceDI
import asyncio

service = RefPortalServiceDI()
asyncio.run(service.start())
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Make sure the project root is in your Python path
2. **Configuration Errors**: Ensure all required environment variables are set
3. **Database Connection Errors**: Check that Redis/DynamoDB is accessible
4. **Container Initialization Errors**: Verify that the container configuration is correct

### Debug Mode

Enable debug logging by setting the environment variable:
```bash
export swLevel=debug
```

## Examples

See the following files for complete examples:
- `test_ref_portal_service_di.py`: Test script demonstrating usage
- `example_usage.py`: General AppContainer usage examples
- `test_app_container.py`: AppContainer testing examples 