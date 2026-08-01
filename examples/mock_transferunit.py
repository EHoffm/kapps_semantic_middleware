"""MockTransferUnit — the edge-device PLC stand-in for scenario 3 (#40, ADR 0023).

Stands in for the decentralized PLC that controls one TransferUnit. It speaks only MQTT and
knows nothing about the middleware, the ontology or the graph: that asymmetry is the point of
the scenario. Everything semantic happens on the middleware side, and the device is exactly
as dumb as a real one.

Publishes 4 — two conveyor speeds and two light-barrier occupancies.
Subscribes to 2 — the two conveyor speed setpoints. A setpoint moves the speed the unit
publishes, which is what closes the loop end to end.

Topic scheme (an instance convention, never baked into the classes — ADR 0023)::

    TransferUnit<n>/<component>/<position>/<param>          # read
    TransferUnit<n>/ConveyorBelt/<position>/speed_set        # setpoint

Payloads are raw JSON scalars, matching the default the MQTT binding expects when a parameter
declares no ``inf:hasMQTTValuePath``.

It publishes **no** ``inf:hasValue`` into the graph, and indeed never touches the graph:
scenario 3 is a locator (ADR 0024). The graph records where a value lives. The live value
exists only in the datamodel and over REST.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Dict, Optional

import aiomqtt

logger = logging.getLogger(__name__)

DEFAULT_BROKER = "127.0.0.1"
DEFAULT_PORT = 1883


class MockTransferUnit:
    """A mock PLC for one TransferUnit, publishing four values and taking two setpoints.

    Publishing is periodic rather than on-change alone. A middleware that starts
    after the device must still converge. ``MqttClientConnector`` holds the latest message
    from its subscription and has nothing to hold until one arrives. A device that only
    published on change would leave a freshly started middleware blank. It would stay blank
    until an operator happened to move something.
    """

    def __init__(
        self,
        unit: str = "TransferUnit1",
        broker: str = DEFAULT_BROKER,
        port: int = DEFAULT_PORT,
        publish_interval: float = 0.5,
        initial_speeds: Optional[Dict[str, float]] = None,
    ) -> None:
        self.unit = unit
        self.broker = broker
        self.port = port
        self.publish_interval = publish_interval

        self.speeds: Dict[str, float] = dict(initial_speeds or {"left": 0.0, "right": 0.0})
        self.occupied: Dict[str, bool] = {"front": False, "back": False}

        self._client: Optional[aiomqtt.Client] = None
        self._tasks: list = []
        self._setpoints_seen = asyncio.Event()

    # --- Topics ------------------------------------------------------------------ #

    def speed_topic(self, position: str) -> str:
        return f"{self.unit}/ConveyorBelt/{position}/speed"

    def speed_set_topic(self, position: str) -> str:
        return f"{self.unit}/ConveyorBelt/{position}/speed_set"

    def occupied_topic(self, position: str) -> str:
        return f"{self.unit}/LightBarrier/{position}/occupied"

    @property
    def published_topics(self) -> list:
        """The four topics this unit publishes."""
        return [self.speed_topic(p) for p in ("left", "right")] + [
            self.occupied_topic(p) for p in ("front", "back")
        ]

    @property
    def subscribed_topics(self) -> list:
        """The two setpoint topics this unit subscribes to."""
        return [self.speed_set_topic(p) for p in ("left", "right")]

    # --- Lifecycle ---------------------------------------------------------------- #

    async def start(self) -> None:
        """Connect, subscribe to both setpoint topics, and begin publishing."""
        self._client = aiomqtt.Client(self.broker, port=self.port)
        await self._client.__aenter__()
        for topic in self.subscribed_topics:
            await self._client.subscribe(topic)
        self._tasks = [
            asyncio.create_task(self._listen()),
            asyncio.create_task(self._publish_loop()),
        ]
        logger.info(
            "MockTransferUnit %s up on %s:%s — publishing %d, subscribed to %d",
            self.unit,
            self.broker,
            self.port,
            len(self.published_topics),
            len(self.subscribed_topics),
        )

    async def stop(self) -> None:
        """Cancel the loops and disconnect."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def __aenter__(self) -> "MockTransferUnit":
        await self.start()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.stop()

    # --- Behavior ---------------------------------------------------------------- #

    async def publish_once(self) -> None:
        """Publish the current value of all four read topics."""
        for position, speed in self.speeds.items():
            await self._publish(self.speed_topic(position), speed)
        for position, occupied in self.occupied.items():
            await self._publish(self.occupied_topic(position), occupied)

    async def set_occupied(self, position: str, occupied: bool) -> None:
        """Move a light barrier and publish it immediately.

        The barriers are read-only northbound, so this is the test entry — it is what a
        workpiece passing the sensor would do.
        """
        self.occupied[position] = occupied
        await self._publish(self.occupied_topic(position), occupied)

    async def wait_for_setpoint(self, timeout: float = 5.0) -> None:
        """Block until at least one setpoint arrives. For tests."""
        await asyncio.wait_for(self._setpoints_seen.wait(), timeout=timeout)

    async def _listen(self) -> None:
        """Apply incoming setpoints and republish the resulting speed."""
        assert self._client is not None
        async for message in self._client.messages:
            topic = str(message.topic)
            position = topic.split("/")[-2] if "/" in topic else ""
            try:
                value = float(json.loads(message.payload.decode()))
            except (ValueError, json.JSONDecodeError):
                logger.warning("Ignoring unparseable setpoint on %s", topic)
                continue

            self.speeds[position] = value
            self._setpoints_seen.set()
            logger.info("%s setpoint -> %s", topic, value)
            # Republish the read topic straight away: a real PLC acknowledges by reporting
            # its new state, and the round trip is what the integration test observes.
            await self._publish(self.speed_topic(position), value)

    async def _publish_loop(self) -> None:
        while True:
            await self.publish_once()
            await asyncio.sleep(self.publish_interval)

    async def _publish(self, topic: str, value) -> None:
        assert self._client is not None
        await self._client.publish(topic, json.dumps(value).encode())


async def main() -> None:  # pragma: no cover - manual run
    """Run a MockTransferUnit until interrupted, against a local broker."""
    logging.basicConfig(level=logging.INFO)
    async with MockTransferUnit():
        await asyncio.Event().wait()


if __name__ == "__main__":  # pragma: no cover - manual run
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
