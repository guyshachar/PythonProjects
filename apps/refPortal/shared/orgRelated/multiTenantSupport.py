import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger
from shared.db import DbClientBase

import sys

class MultiTenantSupport:
    def __init__(self, logger: Logger, dbClient: DbClientBase, mapConfig: dict):
        self.logger = logger
        self.dbClient = dbClient
        self.mapConfig = mapConfig

        self.buildKeyMapping()
        pass

    mappingConfig = {
        'IL': {
            'football': {
                'games': {
                    'תאריך': 'dateText',
                    'יום': 'dow',
                    'מסגרת משחקים': 'tournamentName',
                    'משחק': 'gameTitle',
                    'סבב': 'round',
                    'מחזור': 'fixture',
                    'מגרש': 'field',
                    'סטטוס': 'status',
                    'תפקיד': 'role',
                    'מבקר': 'reviewer',
                    '* שם': '* name',
                    '* סטטוס': '* status',
                    '* דרג': '* level',
                    '* טלפון': '* phone',
                    '* כתובת': '* address',
                    'הערה': 'comment',
                },
                'reviews': {
                    'מס.': 'no.',
                    'תאריך': 'dateText',
                    'שעה': 'timeText',
                    'מסגרת משחקים': 'tournamentName',
                    'משחק': 'gameTitle',
                    'מגרש': 'field',
                    'מחזור': 'fixture',
                    'תפקיד במגרש': 'role',
                    'מבקר': 'reviewer',
                    'ציון': 'reviewGrade',
                },
                'gamesReports': {
                    'תאריך': 'dateText',
                    'מסגרת משחקים': 'tournamentName',
                    'קבוצה ביתית קבוצה אורחת': 'gameTitle',
                    'מח.': 'fixture',
                    'מגרש': 'field',
                    'סטטוס': 'status',
                },
            }
        }
    }

    def buildKeyMapping(self):
        self.key_mapping = {}
        self.reverse_key_mapping = {}
        for countryCode, eventMapping in self.mapConfig.items():
            self.key_mapping[countryCode] = {}
            self.reverse_key_mapping[countryCode] = {}
            for eventType, objTypeMapping in eventMapping.items():
                self.key_mapping[countryCode][eventType] = {}
                self.reverse_key_mapping[countryCode][eventType] = {}
                for objType, key_mapping in objTypeMapping.items():
                    self.key_mapping[countryCode][eventType][objType] = key_mapping
                    self.reverse_key_mapping[countryCode][eventType][objType] = {v: k for k, v in key_mapping.items()}

    def mapList(self, tenantKey, objType, objs):
        try:            
            # Process each game in the current list
            for gamePk, obj in objs.items():
                # Recursively rename all dictionary keys according to the mapping
                mapped_game = self._recursive_rename_keys(tenantKey=tenantKey, objType=objType, data=obj)
                objs[gamePk] = mapped_game
        except Exception as ex:
            self.logger.error(f'mapData', ex)

    def mapItem(self, tenantKey, objType, obj):
        try:            
            # Recursively rename all dictionary keys according to the mapping
            mapped_game = self._recursive_rename_keys(tenantKey=tenantKey, objType=objType, data=obj)
            return mapped_game
        except Exception as ex:
            self.logger.error(f'mapData', ex)

    def _recursive_rename_keys(self, tenantKey, objType, data):
        if isinstance(data, dict):
            # Create a new dictionary with renamed keys
            new_dict = {}
            countryCode = tenantKey.split('#')[0]
            eventType = tenantKey.split('#')[1]
            for key, value in data.items():
                # Get the new key name from mapping, or keep original if not found
                new_key = self.key_mapping.get(countryCode, {}).get(eventType, {}).get(objType, {}).get(key, key)
                # Recursively process the value
                if new_key == 'role' and value in self.key_mapping.get(countryCode, {}).get(eventType, {}).get(objType, {}):
                    new_value = self.key_mapping.get(countryCode, {}).get(eventType, {}).get(objType, {}).get(value, value)
                else:
                    new_value = value
                new_dict[new_key] = self._recursive_rename_keys(tenantKey=tenantKey, objType=objType, data=new_value)
            return new_dict
        elif isinstance(data, list):
            # Process each item in the list recursively
            return [self._recursive_rename_keys(tenantKey=tenantKey, objType=objType, data=item) for item in data]
        else:
            # Return primitive values as-is
            return data
