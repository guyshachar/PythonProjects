# pylint: disable=attribute-defined-outside-init, disable=missing-function-docstring
# pylint: disable=missing-class-docstring, disable=unused-argument
# pylint: disable=missing-module-docstring

import time
import traceback
from queue import Queue
from threading import Event, Thread

import appdaemon.plugins.hass.hassapi as hass
from globals.hal import HAL


class Sound(hass.Hass):
    def initialize(self):
        self.hal = HAL(self)

        # Create Queue
        self.queue = Queue(maxsize=0)

        # Create worker thread
        worker = Thread(target=self.worker)
        worker.daemon = True
        worker.start()

        self.event = Event()

        #
        # Register service
        #
        self.register_service("sound/tts", self.tts_service, namespace="sanctuary")
        self.register_service("sound/play", self.play_service, namespace="sanctuary")

    def worker(self):
        active = True
        while active:
            try:
                # Get data from queue
                volume = {}
                source = {}
                data = self.queue.get()

                if data["type"] == "terminate":
                    active = False
                else:
                    if self.hal.get_state("disable_announcements") == "off":
                        # Save current volume

                        if "player" not in data or data["player"] is None:
                            players = self.args["players"]
                        else:
                            players = [data["player"]]

                        for player in players:
                            volume[player] = self.hal.get_state(player, attribute="volume_level")
                            source[player] = self.hal.get_state(player, attribute="source")
                            # Set to the desired volume
                            self.hal.call_service(
                                "media_player/volume_set",
                                entity_id=player,
                                volume_level=float(data["volume"]),
                            )
                            if data["type"] == "tts":
                                # Call TTS service
                                self.hal.call_service(
                                    "tts/google_translate_say", entity_id=player, message=data["text"]
                                )
                            if data["type"] == "play":
                                netpath = (
                                    f"http://{self.args['ip']}:"
                                    + f"{self.args['port']}/local/{self.args['base']}"
                                    + f"/{data['path']}"
                                )

                                self.log(f"Playing {netpath}")
                                self.hal.call_service(
                                    "media_player/play_media",
                                    entity_id=player,
                                    media_content_id=netpath,
                                    media_content_type=data["content"],
                                )

                        # Wait until current media is done before continuing
                        # Wait a second to avoid race condition
                        time.sleep(1)
                        done = False
                        while not done:
                            done = True
                            for player in players:
                                if self.hal.get_state(player) != "paused":
                                    done = False
                            time.sleep(1)

                        # OK, Reset them all
                        for player in players:
                            # Restore volume
                            if volume[player] is not None:
                                self.hal.call_service(
                                    "media_player/volume_set", entity_id=player, volume_level=volume[player]
                                )
                            if source[player] is not None:
                                self.hal.call_service(
                                    "media_player/select_source", entity_id=player, source=source[player]
                                )
            # pylint: disable=broad-exception-caught
            except Exception:
                self.log("Error processing media request")
                self.log(traceback.format_exc())

            # Wait another couple of seconds
            time.sleep(2)

            # Rinse and repeat
            self.queue.task_done()

        self.log("Worker thread exiting")
        self.event.set()

    def tts_service(self, namespace, domain, service, **data):
        if "player" in data:
            player = data["player"]
        else:
            player = None

        self.tts(data["text"], data["volume"], player)

    def tts(self, text, volume, player=None):
        self.queue.put({"type": "tts", "text": text, "volume": volume, "player": player})

    def play_service(self, namespace, domain, service, **data):
        if "player" in data:
            player = data["player"]
        else:
            player = None

        self.play(data["path"], data["content"], data["volume"], player)

    def play(self, path, content, volume, player=None):
        self.queue.put({"type": "play", "path": path, "content": content, "volume": volume, "player": player})

    def terminate(self):
        self.event.clear()
        self.queue.put({"type": "terminate"})
        self.event.wait()
