# RefPortal Cronjob Client Container

This container runs the RefPortal cronjob client on EC2, handling scheduled tasks and background processing as a continuous service.

## Overview

The cronjob client manages various scheduled tasks for the RefPortal system:

- **Tournament Processing**: Process tournament games and updates
- **Referee Data Collection**: Collect and update referee information
- **Notification Processing**: Handle outgoing notifications
- **System Health Check**: Monitor system health and performance
- **Data Cleanup**: Clean up old data and logs
- **Game Reminders**: Send reminders for upcoming games

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   EC2 Instance  │    │  Cronjob Client  │    │   Task Queue    │
│   (Scheduler)   │───▶│   (Container)    │───▶│   (Database)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │  External APIs   │
                       │  (Twilio, etc.)  │
                       └──────────────────┘
```

## Files

- `Dockerfile` - Container definition for EC2 deployment
- `cronjob_service.py` - Main service for continuous execution
- `lambda_function.py` - Legacy Lambda handler (for compatibility)
- `supervisord.conf` - Process management configuration
- `start.sh` - Container startup script
- `requirements.txt` - Python dependencies
- `docker-compose.yml` - Local development setup
- `README.md` - This documentation

## Dependencies

### Core Dependencies
- `boto3` - AWS SDK
- `schedule` - Task scheduling
- `psutil` - System monitoring
- `asyncio` - Async programming

### RefPortal Dependencies
- `shared/` - Shared modules
- `newServiceArchitecture/` - New architecture modules

### External Services
- `redis` - Caching and task queue
- `firebase-admin` - Firebase integration
- `twilio` - SMS/WhatsApp messaging
- `geopy` - Geocoding services

## Environment Variables

### Required
```bash
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
DYNAMODB_TABLE_NAME=refportal-table
REDIS_URL=redis://localhost:6379
```

### Optional
```bash
LOG_LEVEL=INFO
TZ=Asia/Jerusalem
FIREBASE_PROJECT_ID=your_project_id
TWILIO_ACCOUNT_SID=your_twilio_sid
WHATSAPP_ACCESS_TOKEN=your_whatsapp_token
```

## Usage

### Local Development

1. **Start with Docker Compose**:
   ```bash
   cd rpCronjob
   docker-compose up -d
   ```

2. **Run specific task**:
   ```bash
   docker exec refportal-cronjob-client python -c "
   import asyncio
   from lambda_function import run_specific_task
   asyncio.run(run_specific_task('tournament_processing'))
   "
   ```

### AWS Lambda Deployment

1. **Build the container**:
   ```bash
   ./buildCronjobDocker.sh v1.0.0
   ```

2. **Push to ECR**:
   ```bash
   ./buildCronjobDocker.sh v1.0.0 true
   ```

3. **Deploy Lambda function**:
   ```bash
   aws lambda create-function \
     --function-name refportal-cronjob \
     --package-type Image \
     --code ImageUri=your-account.dkr.ecr.us-east-1.amazonaws.com/refportal-cronjob:v1.0.0 \
     --role arn:aws:iam::your-account:role/lambda-execution-role \
     --timeout 900 \
     --memory-size 512
   ```

### Lambda Event Structure

```json
{
  "action": "run_all",
  "task_id": "tournament_processing",
  "context": {
    "organization_id": "org123",
    "force_refresh": true
  }
}
```

#### Supported Actions

- `run_all` - Run all enabled tasks
- `run_task` - Run specific task (requires `task_id`)
- `get_stats` - Get task statistics
- `enable_task` - Enable a task (requires `task_id`)
- `disable_task` - Disable a task (requires `task_id`)

## Task Configuration

### Default Schedule

```python
# Tournament processing - every 5 minutes
schedule.every(5).minutes.do(run_task, 'tournament_processing')

# Referee data collection - every 10 minutes
schedule.every(10).minutes.do(run_task, 'referee_data_collection')

# Notification processing - every 2 minutes
schedule.every(2).minutes.do(run_task, 'notification_processing')

# Game reminders - every 5 minutes
schedule.every(5).minutes.do(run_task, 'game_reminder')

# System health check - every 15 minutes
schedule.every(15).minutes.do(run_task, 'system_health_check')

# Data cleanup - daily at 2 AM
schedule.every().day.at("02:00").do(run_task, 'data_cleanup')
```

### Custom Tasks

To add custom tasks, create a new class inheriting from `CronjobTask`:

```python
from shared.cronjobClient import CronjobTask

class MyCustomTask(CronjobTask):
    def __init__(self, logger, db_client, messaging_service):
        super().__init__('my_custom_task', 'My Custom Task', 'Description')
        self.logger = logger
        self.db_client = db_client
        self.messaging_service = messaging_service
    
    async def execute(self, context):
        try:
            # Your task logic here
            self.logger.info("Executing custom task")
            return True
        except Exception as ex:
            self.logger.error("Custom task failed", ex)
            return False
```

## Monitoring

### Task Statistics

Each task tracks:
- `run_count` - Total number of executions
- `success_count` - Successful executions
- `error_count` - Failed executions
- `last_run` - Last execution timestamp
- `next_run` - Next scheduled execution
- `success_rate` - Success percentage

### Logs

Logs are written to:
- **Container**: `/var/log/cronjob/`
- **CloudWatch**: If deployed as Lambda
- **Console**: For local development

### Health Checks

The container includes health checks:
- **Docker**: Basic Python import test
- **Lambda**: Function execution test
- **Application**: Task execution monitoring

## Troubleshooting

### Common Issues

1. **Import Errors**:
   ```bash
   # Check Python path
   docker exec refportal-cronjob-client python -c "import sys; print(sys.path)"
   ```

2. **Database Connection**:
   ```bash
   # Test database connectivity
   docker exec refportal-cronjob-client python -c "
   from shared.dbClientBase import DbClientBase
   client = DbClientBase()
   print('Database connected')
   "
   ```

3. **Task Failures**:
   ```bash
   # Check task statistics
   docker exec refportal-cronjob-client python -c "
   from lambda_function import cronjob_client
   stats = cronjob_client.get_all_stats()
   print(stats)
   "
   ```

### Debug Mode

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
docker-compose up
```

## Security

### IAM Permissions

The Lambda execution role needs:
- DynamoDB read/write access
- CloudWatch logs access
- VPC access (if using VPC)
- External API access (Twilio, Firebase, etc.)

### Environment Variables

- Use AWS Secrets Manager for sensitive data
- Rotate API keys regularly
- Use least-privilege IAM policies

## Performance

### Optimization Tips

1. **Memory**: Start with 512MB, adjust based on usage
2. **Timeout**: Set to 15 minutes for long-running tasks
3. **Concurrency**: Limit concurrent executions
4. **Caching**: Use Redis for frequently accessed data

### Scaling

- **Horizontal**: Multiple Lambda instances
- **Vertical**: Increase memory/timeout
- **Scheduling**: Adjust task frequencies

## Contributing

1. Add new tasks in `newServiceArchitecture/cronjobTasks.py`
2. Update this README with new functionality
3. Test locally with Docker Compose
4. Deploy to staging environment first

## License

Same license as RefPortal project.
