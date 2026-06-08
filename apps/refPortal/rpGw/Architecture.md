### RefereeX Service
# Referee Collector
    Trigger by cronjob - every 5 minutes
    Each instance per country/event type, i.e. IL#football=IFA
        The process run per referee
            Collect all relevant data for a referee, i.e. Games & Reviews
            Scan waiting activities, i.e. Approve Game

# Data Analyzer
    Trigger by sqs
    Analyse data from Collector, i.e. classify each game as new, modified, removed

# Tournament Processes Service
    Trigger by cronjob - every 5 minutes
    Run on all tournaments
        On each tournament
            Check all game to be played
                Check for game publishing. i.e. squads published
# Notification
    Trigger by sqs
    Run on all notification events, i.e. New Game/Review, Modified Game/Review, 
        ...Removed Game/Review, Send Reminder
        Send Whatsapp
        Send Push

### SQS
collector-to-data-analyzer-sqs-prod     collector -> data analyzer
collector-to-data-analyzer-sqs-prod     data analyzer -> notification

### RefereeX API
API endpoints
BOT

### RefereeX PWA
Wrap your PWA in a native shell:


### Fields mapping per federation
Local Term      System Term
מגרש            Field
מסגרת משחקים    TournamentName
