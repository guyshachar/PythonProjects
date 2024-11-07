# pylint: disable=attribute-defined-outside-init, disable=missing-class-docstring, disable=unused-argument, disable=missing-module-docstring
import asyncio
import datetime as dt
from typing import Optional

import adbase
import aiohttp


class HyteraMonitor(adbase.ADBase):
    def initialize(self):
        """App initializer."""
        self.adapi = self.get_ad_api()

        # self.args
        self.power_plug: str = self.args["power_plug"]
        self.device_id: int = self.args["device_id"]
        self.elapsed_before_down: int = self.args["elapsed_before_down"]
        self.retries: int = self.args["retries"]
        self.restart_interval: int = self.args["restart_interval"]
        self.api: dict = self.args["api"]

        # state
        self.manual_fix_required = False
        self.retry_count = 0
        self.restart_procedure_task = None

        # schedule async entrypoint
        self.adapi.run_every(
            self._entrypoint_schedule,
            start=self.adapi.get_now(),  # type: ignore
            interval=120,
        )  # type: ignore

    async def main(self) -> None:
        """Main entrypoint."""
        device_data = await self.get_repeater_data()
        elapsed, last_seen_local = self.last_seen(device_data)

        self.adapi.log(
            f"Hytera Repeater last seen online at: {last_seen_local}.", level="DEBUG"
        )

        # Cancel the restart procedure if the callback sees the repeater is up.
        if (
            await self.is_power_on()
            and self.restart_procedure_task
            and not self.restart_procedure_task.done()
            and elapsed <= self.elapsed_before_down
        ):
            self.adapi.log(
                "Repeater is online and a restart procedure task is running, cancelling task...",
                level="INFO",
            )
            await self.notify_online(last_seen_local)
            await self.cancel_restart_procedure()

        # Repeater connected to network after manually fixed.
        elif (
            await self.is_power_on()
            and elapsed <= self.elapsed_before_down
            and self.manual_fix_required
        ):
            self.adapi.log("ONLINE after being manually fixed.", level="INFO")
            await self.send_notification(
                "Hytera: Manually fixed",
                f"Machine was manually fixed and last seen at {last_seen_local}.",
            )
            self.manual_fix_required = False
            self.retry_count = 0
            self.log_state_data()

        # Start the restart procedure
        elif (
            await self.is_power_on()
            and elapsed > self.elapsed_before_down
            and not self.manual_fix_required
        ) and (
            not self.restart_procedure_task
            or self.restart_procedure_task
            and self.restart_procedure_task.done()
        ):
            self.restart_procedure_task = asyncio.create_task(
                self.run_restart_procedure(device_data, elapsed, last_seen_local)
            )

        elif self.manual_fix_required:
            self.adapi.log(
                "Repeater is offline and a manual fix is required, doing nothing.",
                level="DEBUG",
            )

        elif self.restart_procedure_task:
            self.adapi.log(
                "Repeater is offline and is running through a restart cycle, doing nothing.",
                level="DEBUG",
            )

    async def cancel_restart_procedure(self):
        """Cancel the restart procedure and perform cleanup on state data."""
        if (
            not self.restart_procedure_task
            or self.restart_procedure_task
            and self.restart_procedure_task.done()
        ):
            return None

        try:
            self.restart_procedure_task.cancel()
        except asyncio.CancelledError:
            await self.send_notification(
                "Hytera: Online",
                "Repeater is online before reset procedure could finish, task cancelled.",
            )
            raise
        finally:
            self.restart_procedure_task = None
            self.retry_count = 0
            self.manual_fix_required = False
            self.log_state_data()

    async def run_restart_procedure(
        self,
        device_data: Optional[dict] = None,
        elapsed: Optional[int] = None,
        last_seen_local: Optional[dt.datetime] = None,
    ) -> None:
        """Runs the restart procedure."""
        self.adapi.log("WARNING: Repeater is restarting.", level="WARNING")

        self.adapi.create_task(
            self.send_notification(
                "Hytera: Restarting",
                f"Repeater has not been seen since: {last_seen_local}.",
            )  # type: ignore
        )

        while self.retry_count < self.retries:
            self.log_state_data()
            if (
                self.retry_count > 0
                or not device_data
                or not elapsed
                or not last_seen_local
            ):
                device_data = await self.get_repeater_data()
                elapsed, last_seen_local = self.last_seen(device_data)

            # Device is considered online.
            if elapsed <= self.elapsed_before_down:
                self.adapi.log(
                    f"ONLINE after {self.retry_count} retries.", level="INFO"
                )
                await self.notify_online(last_seen_local)
                self.retry_count = 0
                self.log_state_data()
                break

            # Attempt to fix issue with power cycle procedure.
            self.retry_count += 1
            self.adapi.log(
                f"Increased retry count to: {self.retry_count}", level="DEBUG"
            )
            await self.turn_off()
            await asyncio.sleep(self.restart_interval)
            await self.turn_on()
            await asyncio.sleep(self.elapsed_before_down)

        # Repeater failed to come back online after retries.
        if self.retry_count >= self.retries and not self.manual_fix_required:
            self.manual_fix_required = True
            self.adapi.log("WARNING: manual intervention is required.", level="WARNING")
            await self.send_notification(
                "Hytera: Warning",
                (
                    f"Repeater did not come back online after: {self.retry_count} power cycles. "
                    f"Manual intervention is required. Last seen at {last_seen_local}"
                ),
            )

    async def get_repeater_data(self) -> dict:
        """Return device information from Brandmeister API"""
        url = f"{self.api['url']}/device/{self.device_id}"
        headers = {"Authorization": f"Bearer {self.api['token']}"}
        async with aiohttp.ClientSession(headers=headers) as session:
            resp = await session.get(url)
            if resp.status != 200:
                raise aiohttp.ClientError(
                    f"Unable to connect, response code: {resp.status}"
                )
            return await resp.json()

    async def is_power_on(self) -> bool:
        """Returns True if power is on otherwise return False."""
        state: str = await self.adapi.get_state(self.power_plug, copy=False)
        if state.lower() == "on":
            return True
        return False

    def last_seen(self, device_data: dict) -> tuple[int, dt.datetime]:
        """Returns a tuple with seconds elapsed and timezone aware datetime
        that the repeater was last seen."""
        last_seen = device_data["last_seen"]
        last_seen_obj, elapsed = self._calculate_elapsed(last_seen)
        last_seen_local = last_seen_obj.astimezone()
        return elapsed, last_seen_local

    def log_state_data(self):
        """Log all state data to the console in DEBUG mode."""
        self.adapi.log(
            f"self.manual_fix_required: {self.manual_fix_required}", level="DEBUG"
        )
        self.adapi.log(f"self.retry_count: {self.retry_count}", level="DEBUG")

        if self.restart_procedure_task:
            self.adapi.log(
                f"self.restart_procedure_task: {self.restart_procedure_task}",
                level="DEBUG",
            )

    async def notify_online(self, last_seen_local):
        """Helper method to send notification that repeater is online."""
        await self.send_notification(
            "Hytera: Online",
            (
                f"Repeater is back online after {self.retry_count} power cycles. "
                f"It was last seen online at: {last_seen_local}."
            ),
        )

    async def send_notification(self, title, message) -> None:
        """Send a notification."""
        await self.adapi.call_service(
            "notify/mobile_app_justin_iphone", title=title, message=message
        )

    async def turn_off(self) -> None:
        """Turn off device."""
        await self.adapi.call_service("switch/turn_off", entity_id=self.power_plug)

    async def turn_on(self) -> None:
        """Turn on device."""
        await self.adapi.call_service("switch/turn_on", entity_id=self.power_plug)

    async def terminate(self):
        """Wait for restart procedure to cancel"""
        if self.restart_procedure_task:
            message = (
                "App is closing while the restart procedure is running, cancelling..."
            )
            self.adapi.log(message, level="WARNING")
            await self.send_notification("Hytera: Error", message)
            await self.cancel_restart_procedure()

    def _calculate_elapsed(self, datetime_iso: str) -> tuple[dt.datetime, int]:
        """Returns the amount of seconds elapsed since provided UTC datetime in ISO format."""
        dt_obj = dt.datetime.fromisoformat(datetime_iso).replace(tzinfo=dt.timezone.utc)
        elapsed = (dt.datetime.now(tz=dt.timezone.utc) - dt_obj).seconds
        return dt_obj, elapsed

    def _entrypoint_schedule(self, kwargs):
        """Scheduler callback that creates the async task entrypoint."""
        self.adapi.create_task(self.main())  # type: ignore
