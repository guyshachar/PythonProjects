import boto3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys, os, logging
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(os.path.join(os.path.dirname(__file__), "packages"))
from shared.db import DbClientBase
from shared.db import DynamodbClient

# Create Cost Explorer client
client = boto3.client('ce')

dbClient = DynamodbClient(env=os.getenv('app_env'), logger=logging.getLogger(), awsRegion=os.getenv('awsRegion'), endpointUrl=os.getenv('dynamoDbEndpointUrl'))

# Define time range: yesterday to today
end = datetime.now(timezone.utc)
start = end.date() - timedelta(days=7)

metrics = Metrics=['UnblendedCost', 'UsageQuantity']

response = client.get_cost_and_usage(
    TimePeriod={
        'Start': start.strftime('%Y-%m-%d'),
        'End': end.strftime('%Y-%m-%d')
    },
    Granularity='DAILY',
    Metrics=metrics,
    GroupBy=[
        {'Type': 'DIMENSION', 'Key': 'SERVICE'}
    ]
)

rows = dbClient.getDict('lambdaInvocationsTracking')

# Process and display
for day_data in response['ResultsByTime']:
    day = day_data['TimePeriod']['Start']
    groups = day_data['Groups']

    print(f"\n📅 Date: {day}")
    daily_total_cost = 0.0
    daily_total_usage = 0.0

    dailyRows = [ { value['created'].strftime('%Y-%m-%dT%H'): value } for key, value in rows.items() if value['created'].strftime('%Y-%m-%d') == day ]

    for group in groups:
        service = group['Keys'][0]
        amount = float(group['Metrics']['UnblendedCost']['Amount'])
        usage = float(group['Metrics']['UsageQuantity']['Amount'])
        daily_total_cost += amount
        daily_total_usage += usage
        print(f"  - {service}: ${amount:,.4f} {usage:,.2f}s")

    print(f"🧾 Daily Total: ${daily_total_cost:,.4f} {daily_total_usage:,.2f}s Invocations: {len(dailyRows)}")
