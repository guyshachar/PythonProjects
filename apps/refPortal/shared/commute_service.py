import math
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Union, Tuple, List
import requests
from datetime import timedelta

import shared.helpers as helpers
from shared.logger import Logger


class CommuteService:
    """Travel time estimation using Google Routes API (routes.googleapis.com).
    Falls back to haversine straight-line estimate when no API key is configured."""

    _ROUTES_COMPUTE_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
    _DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
    _ROAD_FACTOR = 1.35  # straight-line to road-distance multiplier for haversine fallback
    _AVG_SPEED_KMH = 40  # conservative urban average for haversine fallback

    def __init__(self, logger: Logger, google_maps_api_key_server: Optional[str] = None):
        self.logger = logger
        self._api_key = google_maps_api_key_server
        self.has_live_data = False
        if not self._api_key:
            self.logger.warning(
                "CommuteService: no google_maps_api_key_server — using haversine estimates only"
            )

    def _log_google_api_error(self, api_name: str, resp: requests.Response, data: dict) -> None:
        err = data.get("error") or {}
        code = err.get("code", resp.status_code)
        message = err.get("message") or data.get("error_message") or resp.text[:300]
        status = err.get("status") or data.get("status") or resp.reason
        self.logger.warning(
            f"{api_name} error ({code} {status}): {message}. "
            "For Routes API: enable 'Routes API' (routes.googleapis.com) on the GCP project "
            "and allow it on google_maps_api_key_server. "
            "Falling back to Directions API / haversine when possible."
        )

    @staticmethod
    def _routes_response_has_error(resp: requests.Response, data: dict) -> bool:
        return not resp.ok or bool(data.get("error")) or not data.get("routes")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _headers(self, field_mask: str) -> dict:
        return {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": field_mask,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _latlng(coords: Dict) -> dict:
        return {"latLng": {"latitude": float(coords["lat"]), "longitude": float(coords["lng"])}}

    @staticmethod
    def _waypoint_from_coords(coords: Dict) -> dict:
        return {"location": CommuteService._latlng(coords)}

    @staticmethod
    def _waypoint_from_address(address: str) -> dict:
        return {"address": address}

    @staticmethod
    def _parse_duration_s(d) -> int:
        """Parse Routes API duration value: '123.4s' string or dict → int seconds."""
        if isinstance(d, dict):
            return int(d.get("seconds", d.get("value", 0)))
        s = str(d).rstrip("s")
        return int(float(s)) if s else 0

    @staticmethod
    def _departure_iso(departure_time: Optional[Union[int, str]]) -> Optional[str]:
        """Convert unix timestamp or 'now' to RFC3339 UTC string for Routes API."""
        if departure_time is None:
            return None
        if departure_time == "now":
            return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return datetime.fromtimestamp(int(departure_time), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------
    # Public interface (same signatures as before)
    # ------------------------------------------------------------------

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
            pair = self._routes_point_to_point(
                origin=origin,
                origin_coords=origin_coords,
                destination_coords=destination_coords,
                destination_address=destination_address,
                departure_time=departure_time,
            )
            if pair is not None:
                self.has_live_data = True
                return pair[0] // 60

        if origin_coords and destination_coords:
            return self._haversine_estimate(origin_coords, destination_coords)

        return 30

    async def get_driving_route_seconds_meters(
        self,
        origin_coords: Dict,
        dest_coords: Dict,
        departure_time: Optional[Union[int, str]] = None,
    ) -> Tuple[Optional[int], Optional[int]]:
        """Driving route as (duration_seconds, distance_meters)."""
        if not origin_coords or not origin_coords.get('lat') or not origin_coords.get('lng') or not dest_coords or not dest_coords.get('lat') or not dest_coords.get('lng'):
            return None, None
        
        if self._api_key:
            pair = self._routes_point_to_point(
                origin_coords=origin_coords,
                destination_coords=dest_coords,
                departure_time=departure_time,
            )
            if pair is not None:
                self.has_live_data = True
                return pair

        minutes = self._haversine_estimate(origin_coords, dest_coords)
        meters = self._haversine_distance_meters(origin_coords, dest_coords)
        return minutes * 60, meters

    async def plan_carpool_route(
        self,
        driver_coords: Dict,
        passenger_coords_list: List[Dict],
        destination_coords: Dict,
        destination_address: Optional[str] = None,
        departure_time: Optional[Union[int, str]] = None,
    ) -> Optional[Dict]:
        """
        Plan optimal carpool route: driver origin → ordered pickup stops → destination.
        Uses Routes API computeRoutes with optimizeWaypointOrder=true.
        Each item in passenger_coords_list must have lat/lng and optionally mobileNo/name/address.
        Returns totalDurationMinutes, totalDistanceKm, stops, destination, googleMapsUrl.
        """
        if not passenger_coords_list:
            return None

        if not self._api_key:
            return self._carpool_fallback(driver_coords, passenger_coords_list, destination_coords, destination_address)

        body: Dict = {
            "origin": {"location": self._latlng(driver_coords)},
            "destination": (
                self._waypoint_from_address(destination_address)
                if destination_address
                else {"location": self._latlng(destination_coords)}
            ),
            "intermediates": [
                {"location": self._latlng({"lat": p["lat"], "lng": p["lng"]})}
                for p in passenger_coords_list
            ],
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "optimizeWaypointOrder": True,
            "languageCode": "he",
        }
        dep = self._departure_iso(departure_time)
        if dep > helpers.utcNow().isoformat():
            body["departureTime"] = dep

        field_mask = (
            "routes.duration,routes.distanceMeters,"
            "routes.optimizedIntermediateWaypointIndex,"
            "routes.legs.duration,routes.legs.distanceMeters"
        )

        try:
            resp = requests.post(
                self._ROUTES_COMPUTE_URL,
                headers=self._headers(field_mask),
                json=body,
                timeout=10,
            )
            data = resp.json()

            if self._routes_response_has_error(resp, data):
                self._log_google_api_error("Routes API (carpool)", resp, data)
                return self._carpool_fallback(driver_coords, passenger_coords_list, destination_coords, destination_address)

            route = data["routes"][0]
            waypoint_order: List[int] = route.get(
                "optimizedIntermediateWaypointIndex",
                list(range(len(passenger_coords_list))),
            )
            legs = route["legs"]

            stops = []
            cumulative_minutes = 0
            for seq, orig_idx in enumerate(waypoint_order):
                passenger = passenger_coords_list[orig_idx]
                leg_seconds = self._parse_duration_s(legs[seq].get("duration", "0s"))
                leg_minutes = leg_seconds // 60
                cumulative_minutes += leg_minutes
                lat, lng = passenger["lat"], passenger["lng"]
                stops.append({
                    "mobileNo": passenger.get("mobileNo", ""),
                    "name": passenger.get("name", ""),
                    "address": passenger.get("address", ""),
                    "coords": {"lat": lat, "lng": lng},
                    "legDurationMinutes": leg_minutes,
                    "cumulativeDurationMinutes": cumulative_minutes,
                    "wazeUrl": f"waze://?ll={lat},{lng}&navigate=yes",
                })

            last_leg_seconds = self._parse_duration_s(legs[len(waypoint_order)].get("duration", "0s"))
            cumulative_minutes += last_leg_seconds // 60
            total_meters = int(route.get("distanceMeters", 0))

            origin_str = f'{driver_coords["lat"]},{driver_coords["lng"]}'
            ordered_pax = [passenger_coords_list[i] for i in waypoint_order]
            wp_coords = "/".join(f'{p["lat"]},{p["lng"]}' for p in ordered_pax)
            dest_coord_str = f'{destination_coords["lat"]},{destination_coords["lng"]}'
            google_maps_url = f"https://www.google.com/maps/dir/{origin_str}/{wp_coords}/{dest_coord_str}"

            return {
                "totalDurationMinutes": cumulative_minutes,
                "totalDistanceKm": round(total_meters / 1000, 1) if total_meters else None,
                "stops": stops,
                "destination": {"address": destination_address or "", "coords": destination_coords},
                "googleMapsUrl": google_maps_url,
                "computedAt": helpers.localNow().isoformat(),
                "hasTrafficData": True,
            }

        except Exception as ex:
            self.logger.warning(f"Routes API error — falling back to haversine: {ex}")
            return self._carpool_fallback(driver_coords, passenger_coords_list, destination_coords, destination_address)

    # ------------------------------------------------------------------
    # Private — computeRoutes point-to-point (no intermediates)
    # ------------------------------------------------------------------

    def _directions_point_to_point(
        self,
        origin: Optional[str] = None,
        origin_coords: Optional[Dict] = None,
        destination_coords: Optional[Dict] = None,
        destination_address: Optional[str] = None,
        departure_time: Optional[Union[int, str]] = None,
    ) -> Optional[Tuple[int, int]]:
        """Legacy Directions API fallback when Routes API is unavailable."""
        try:
            params: Dict = {
                "key": self._api_key,
                "mode": "driving",
                "language": "he",
            }
            if origin:
                params["origin"] = origin
            elif origin_coords:
                params["origin"] = f"{origin_coords['lat']},{origin_coords['lng']}"
            else:
                return None

            if destination_address:
                params["destination"] = destination_address
            elif destination_coords:
                params["destination"] = f"{destination_coords['lat']},{destination_coords['lng']}"
            else:
                return None

            if departure_time is not None:
                params["departure_time"] = (
                    "now" if departure_time == "now" else int(departure_time)
                )

            resp = requests.get(self._DIRECTIONS_URL, params=params, timeout=5)
            data = resp.json()
            if data.get("status") != "OK" or not data.get("routes"):
                self._log_google_api_error("Directions API", resp, data)
                return None

            leg = data["routes"][0]["legs"][0]
            return int(leg["duration"]["value"]), int(leg["distance"]["value"])
        except Exception as ex:
            self.logger.warning(f"Directions API point-to-point error: {ex}")
        return None

    def _routes_point_to_point(
        self,
        origin: Optional[str] = None,
        origin_coords: Optional[Dict] = None,
        destination_coords: Optional[Dict] = None,
        destination_address: Optional[str] = None,
        departure_time: Optional[Union[int, str]] = None,
    ) -> Optional[Tuple[int, int]]:
        """Single origin→destination via computeRoutes. Returns (seconds, meters)."""
        try:
            body: Dict = {
                "origin": (
                    self._waypoint_from_address(origin)
                    if origin
                    else self._waypoint_from_coords(origin_coords)
                ),
                "destination": (
                    self._waypoint_from_address(destination_address)
                    if destination_address
                    else self._waypoint_from_coords(destination_coords)
                ),
                "travelMode": "DRIVE",
                "routingPreference": "TRAFFIC_AWARE",
                "languageCode": "he",
            }
            dep = self._departure_iso(departure_time)
            if dep and dep > helpers.utcNow().isoformat():
                body["departureTime"] = dep

            resp = requests.post(
                self._ROUTES_COMPUTE_URL,
                headers=self._headers("routes.duration,routes.distanceMeters"),
                json=body,
                timeout=5,
            )
            data = resp.json()
            if not self._routes_response_has_error(resp, data):
                route = data["routes"][0]
                return (
                    self._parse_duration_s(route.get("duration", "0s")),
                    int(route.get("distanceMeters", 0)),
                )

            self._log_google_api_error("Routes API", resp, data)
            return self._directions_point_to_point(
                origin=origin,
                origin_coords=origin_coords,
                destination_coords=destination_coords,
                destination_address=destination_address,
                departure_time=departure_time,
            )
        except Exception as e:
            self.logger.warning(f"Routes API point-to-point error: {e}")
        return None

    # ------------------------------------------------------------------
    # Private — haversine fallback
    # ------------------------------------------------------------------

    def _carpool_fallback(
        self,
        driver_coords: Dict,
        passenger_coords_list: List[Dict],
        destination_coords: Dict,
        destination_address: Optional[str],
    ) -> Dict:
        cumulative_minutes = 0
        stops = []
        prev = driver_coords
        for p in passenger_coords_list:
            p_coords = {"lat": p["lat"], "lng": p["lng"]}
            leg_minutes = self._haversine_estimate(prev, p_coords)
            cumulative_minutes += leg_minutes
            stops.append({
                "mobileNo": p.get("mobileNo", ""),
                "name": p.get("name", ""),
                "address": p.get("address", ""),
                "coords": p_coords,
                "legDurationMinutes": leg_minutes,
                "cumulativeDurationMinutes": cumulative_minutes,
                "wazeUrl": f"waze://?ll={p['lat']},{p['lng']}&navigate=yes",
            })
            prev = p_coords
        cumulative_minutes += self._haversine_estimate(prev, destination_coords)
        return {
            "totalDurationMinutes": cumulative_minutes,
            "totalDistanceKm": None,
            "stops": stops,
            "destination": {"address": destination_address or "", "coords": destination_coords},
            "googleMapsUrl": None,
            "computedAt": helpers.localNow().isoformat(),
            "hasTrafficData": False,
        }

    def _haversine_estimate(self, origin: Dict, destination: Dict) -> int:
        lat1, lon1 = math.radians(float(origin["lat"])), math.radians(float(origin["lng"]))
        lat2, lon2 = math.radians(float(destination["lat"])), math.radians(float(destination["lng"]))
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        distance_km = 2 * math.asin(math.sqrt(a)) * 6371 * self._ROAD_FACTOR
        return max(int((distance_km / self._AVG_SPEED_KMH) * 60), 5)

    def _haversine_distance_meters(self, origin: Dict, destination: Dict) -> int:
        lat1, lon1 = math.radians(float(origin["lat"])), math.radians(float(origin["lng"]))
        lat2, lon2 = math.radians(float(destination["lat"])), math.radians(float(destination["lng"]))
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return int(2 * math.asin(math.sqrt(a)) * 6371 * self._ROAD_FACTOR * 1000)


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
