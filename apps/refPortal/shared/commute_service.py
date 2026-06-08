import math
import asyncio
from typing import Optional, Dict, Union, Tuple
import requests
from datetime import timedelta

import shared.helpers as helpers
from shared.logger import Logger


class CommuteService:
    """Travel time estimation. Uses Google Maps Distance Matrix API (driving) when a key is
    configured, otherwise falls back to a haversine straight-line estimate.

    Optional ``departure_time`` (Unix seconds or ``\"now\"``) enables traffic-aware
    duration when the API returns ``duration_in_traffic``."""

    _GOOGLE_MAPS_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
    _ROAD_FACTOR = 1.35  # straight-line to road-distance multiplier
    _AVG_SPEED_KMH = 40  # conservative urban average

    def __init__(self, logger: Logger, google_maps_api_key_server: Optional[str] = None):
        self.logger = logger
        self._api_key = google_maps_api_key_server
        self.has_live_data = False

    async def get_travel_minutes(
        self,
        origin: Optional[str] = None,
        origin_coords: Optional[Dict] = None,
        destination_coords: Optional[Dict] = None,
        destination_address: Optional[str] = None,
        departure_time: Optional[Union[int, str]] = None,
    ) -> int:
        if not origin and not origin_coords:
            return 30

        if self._api_key:
            origin_str = origin or f'{origin_coords["lat"]},{origin_coords["lng"]}'
            dest_str = destination_address or (
                f'{destination_coords["lat"]},{destination_coords["lng"]}' if destination_coords else None
            )
            if dest_str:
                minutes = self._google_maps(
                    origin_str,
                    dest_str,
                    departure_time=departure_time,
                )
                if minutes is not None:
                    self.has_live_data = True
                    return minutes

        if origin_coords and destination_coords:
            return self._haversine_estimate(origin_coords, destination_coords)

        return 30

    async def get_driving_route_seconds_meters(
        self,
        origin_coords: Dict,
        dest_coords: Dict,
        departure_time: Optional[Union[int, str]] = None,
    ) -> Tuple[Optional[int], Optional[int]]:
        """Driving route as (duration_seconds, distance_meters). Uses Distance Matrix when keyed; else haversine."""
        if self._api_key:
            origin_str = f'{origin_coords["lat"]},{origin_coords["lng"]}'
            dest_str = f'{dest_coords["lat"]},{dest_coords["lng"]}'
            pair = self._google_maps_seconds_meters(
                origin_str, dest_str, departure_time=departure_time
            )
            if pair is not None:
                self.has_live_data = True
                return pair

        minutes = self._haversine_estimate(origin_coords, dest_coords)
        meters = self._haversine_distance_meters(origin_coords, dest_coords)
        return minutes * 60, meters

    def _google_maps_seconds_meters(
        self,
        origin: str,
        destination: str,
        *,
        departure_time: Optional[Union[int, str]] = None,
    ) -> Optional[Tuple[int, int]]:
        try:
            params = {
                "origins": origin,
                "destinations": destination,
                "mode": "driving",
                "key": self._api_key,
                "language": "he",
            }
            if departure_time is not None:
                params["departure_time"] = int(departure_time)
            resp = requests.get(self._GOOGLE_MAPS_URL, params=params, timeout=5)
            data = resp.json()
            element = data["rows"][0]["elements"][0]
            if element["status"] == "OK":
                dur = element.get("duration_in_traffic") or element["duration"]
                dist = element["distance"]
                return int(dur["value"]), int(dist["value"])
        except Exception as e:
            self.logger.warning("Google Maps API error:", e)
        return None

    def _google_maps(
        self,
        origin: str,
        destination: str,
        *,
        departure_time: Optional[Union[int, str]] = None,
    ) -> Optional[int]:
        pair = self._google_maps_seconds_meters(
            origin, destination, departure_time=departure_time
        )
        if pair is not None:
            return pair[0] // 60
        return None

    def _haversine_distance_meters(self, origin: Dict, destination: Dict) -> int:
        lat1 = math.radians(origin["lat"])
        lon1 = math.radians(origin["lng"])
        lat2 = math.radians(destination["lat"])
        lon2 = math.radians(destination["lng"])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        distance_km = 2 * math.asin(math.sqrt(a)) * 6371 * self._ROAD_FACTOR
        return int(distance_km * 1000)

    def _haversine_estimate(self, origin: Dict, destination: Dict) -> int:
        lat1 = math.radians(origin["lat"])
        lon1 = math.radians(origin["lng"])
        lat2 = math.radians(destination["lat"])
        lon2 = math.radians(destination["lng"])

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        distance_km = 2 * math.asin(math.sqrt(a)) * 6371 * self._ROAD_FACTOR

        minutes = int((distance_km / self._AVG_SPEED_KMH) * 60)
        return max(minutes, 5)


if __name__ == '__main__':
    from shared.appContainer import AppContainer

    container = AppContainer.getAppContainer()
    commuteService: CommuteService = container.commute_service()
    now = helpers.localNow()
    departure_time = now + timedelta(hours=12)
    minutes = asyncio.run(
        commuteService.get_travel_minutes(
            origin='Tel Aviv',
            destination_address='Jerusalem',
            departure_time=departure_time.timestamp(),
        )
    )
    print(minutes)
