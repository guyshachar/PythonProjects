import sys
import time
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import httpx
import jwt as pyjwt
import shared.helpers as helpers
from shared.logger import Logger
from shared.configManager import ConfigManager


class ApnsClient:
    """Sends alert pushes to the iOS app via Apple Push Notification service (HTTP/2, token-based auth).

    Sibling to the inline VAPID web-push handling in MessagingService.sendPushNotification - same
    one-way "push to a stored subscription" shape, just a different wire protocol/auth scheme.
    """

    # Apple asks that JWT auth tokens not be regenerated more than once per ~20 minutes;
    # cache generously below their ~60 minute expiry window.
    _TOKEN_MAX_AGE_SECONDS = 50 * 60

    def __init__(self, logger: Logger, config: dict = None, useClient: bool = True):
        self.logger = logger
        self.config = config or {}
        self.useClient = useClient

        self.authKey = helpers.get_secret('apns_auth_key')
        self.keyId = helpers.get_secret('apns_key_id')
        self.teamId = helpers.get_secret('apns_team_id')
        self.bundleId = ConfigManager.get_config_value(self.config, 'apnsBundleId', 'com.refereex.RefPortal')
        useSandbox = ConfigManager.get_config_bool(self.config, 'apnsUseSandbox', True)
        self.host = 'https://api.sandbox.push.apple.com' if useSandbox else 'https://api.push.apple.com'

        self._token = None
        self._tokenIssuedAt = 0.0

        self.logger.info(f'ApnsClient starts... useClient={useClient}, sandbox={useSandbox}')

    def _bearerToken(self) -> str:
        now = time.time()
        if self._token and (now - self._tokenIssuedAt) < self._TOKEN_MAX_AGE_SECONDS:
            return self._token
        self._token = pyjwt.encode(
            {'iss': self.teamId, 'iat': int(now)},
            self.authKey,
            algorithm='ES256',
            headers={'kid': self.keyId}
        )
        self._tokenIssuedAt = now
        return self._token

    def send(self, deviceToken: str, title: str, body: str = None, gameId: str = None, section: str = None, badge: int = None, category: str = None, leaveByTime: str = None) -> dict:
        """Returns {'success': bool, 'expired': bool} - 'expired' tells the caller to drop the stored token."""
        if not self.useClient:
            self.logger.info(f'ApnsClient.send skipped (useClient=False) title={title}')
            return {'success': False, 'expired': False}
        if not deviceToken or not self.authKey or not self.keyId or not self.teamId:
            return {'success': False, 'expired': False}

        payload = {'aps': {'alert': {'title': title or 'RefereeX', 'body': body or ''}, 'sound': 'default'}}
        if badge is not None:
            payload['aps']['badge'] = badge
        if category:
            # Tells the iOS UNUserNotificationCenter which action buttons to show
            # (see NotificationService.swift's registerCategories) - e.g. approve/ignore on a
            # new game assignment push.
            payload['aps']['category'] = category
        if gameId:
            # Named tournamentGameId on the wire (not gameId) - matches what
            # clientApproveGame/approveGame actually expect and what the client should use to
            # act on this push, since tenantKey is unnecessary (approveGame resolves it itself).
            payload['tournamentGameId'] = gameId
        if section:
            payload['section'] = section
        if leaveByTime:
            # ISO8601 - iOS schedules a local "time to leave" notification off this
            # (leaveByTime - 10min) rather than the server polling/re-computing it.
            payload['leaveByTime'] = leaveByTime

        headers = {
            'authorization': f'bearer {self._bearerToken()}',
            'apns-topic': self.bundleId,
            'apns-push-type': 'alert',
            'apns-priority': '10',
        }

        try:
            with httpx.Client(http2=True, timeout=10) as client:
                response = client.post(f'{self.host}/3/device/{deviceToken}', headers=headers, json=payload)
            if response.status_code == 200:
                return {'success': True, 'expired': False}
            expired = response.status_code == 410 or (response.status_code == 400 and 'BadDeviceToken' in response.text)
            self.logger.warning(f'ApnsClient.send failed status={response.status_code} body={response.text}')
            return {'success': False, 'expired': expired}
        except Exception as ex:
            self.logger.error('ApnsClient.send', ex)
            return {'success': False, 'expired': False}
