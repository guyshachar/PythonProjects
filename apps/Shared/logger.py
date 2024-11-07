import logging

# Create a custom formatter that includes the logger name
class CustomFormatter(logging.Formatter):
    def format(self, record):
        record.logger_name = record.name  # Add the logger name as a custom attribute
        return super(CustomFormatter, self).format(record)

# Create a logger
class Logger:
    def __init__(self, obj):
        logger = logging.getLogger(obj.__class__.__name__)
        logger.setLevel(logging.INFO)  # Set the logging level
        
        # Create a handler and set the custom formatter
        handler = logging.StreamHandler()
        formatter = CustomFormatter('%(asctime)s - %(logger_name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        
        # Add the handler to the logger
        logger.addHandler(handler)
        obj.logger = logger    
