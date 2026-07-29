"""MockTransferUnit against a real broker (#40).

Live MQTT: a pure-Python ``amqtt`` broker in-process, real sockets, the same ``aiomqtt``
client the framework connector uses. No GraphDB — this is the device half of scenario 3, and
the device knows nothing about the graph.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiomqtt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from mock_transferunit import MockTransferUnit  # noqa: E402


async def _collect(broker: str, topics, count, timeout=5.0):
    """Subscribe to `topics` and return the first `count` messages as (topic, value)."""
    host, port = broker.split(":")
    received = []
    async with aiomqtt.Client(host, port=int(port)) as client:
        for topic in topics:
            await client.subscribe(topic)

        async def pump():
            async for message in client.messages:
                received.append(
                    (str(message.topic), json.loads(message.payload.decode()))
                )
                if len(received) >= count:
                    return

        await asyncio.wait_for(pump(), timeout=timeout)
    return received


class TestTopicScheme:
    """The scheme is TransferUnit<n>/<component>/<position>/<param>, +_set (ADR 0023)."""

    def test_publishes_four_topics(self):
        unit = MockTransferUnit()

        assert unit.published_topics == [
            "TransferUnit1/ConveyorBelt/left/speed",
            "TransferUnit1/ConveyorBelt/right/speed",
            "TransferUnit1/LightBarrier/front/occupied",
            "TransferUnit1/LightBarrier/back/occupied",
        ]

    def test_subscribes_to_two_topics(self):
        unit = MockTransferUnit()

        assert unit.subscribed_topics == [
            "TransferUnit1/ConveyorBelt/left/speed_set",
            "TransferUnit1/ConveyorBelt/right/speed_set",
        ]

    def test_the_unit_name_parameterises_every_topic(self):
        """Multiple simultaneous TransferUnits are in scope for map #24."""
        unit = MockTransferUnit(unit="TransferUnit7")

        assert all(t.startswith("TransferUnit7/") for t in unit.published_topics)
        assert all(t.startswith("TransferUnit7/") for t in unit.subscribed_topics)


@pytest.mark.asyncio
class TestLiveBehaviour:
    async def test_publishes_all_four_values(self, mqtt_broker):
        host, port = mqtt_broker.split(":")
        async with MockTransferUnit(broker=host, port=int(port), publish_interval=0.1) as unit:
            received = await _collect(mqtt_broker, unit.published_topics, count=4)

        assert {topic for topic, _ in received} == set(unit.published_topics)

    async def test_a_setpoint_moves_the_published_speed(self, mqtt_broker):
        """#40's acceptance: a setpoint on speed_set moves the published speed."""
        host, port = mqtt_broker.split(":")
        async with MockTransferUnit(
            broker=host, port=int(port), publish_interval=0.1
        ) as unit:
            assert unit.speeds["left"] == 0.0

            async with aiomqtt.Client(host, port=int(port)) as publisher:
                await publisher.publish(
                    "TransferUnit1/ConveyorBelt/left/speed_set", json.dumps(1.75).encode()
                )
                await unit.wait_for_setpoint()

            assert unit.speeds["left"] == 1.75

            # And the new value reaches the read topic, which is what a middleware sees.
            speeds = await _collect(
                mqtt_broker, ["TransferUnit1/ConveyorBelt/left/speed"], count=1
            )
            assert speeds[0][1] == 1.75

    async def test_a_setpoint_does_not_disturb_the_other_belt(self, mqtt_broker):
        host, port = mqtt_broker.split(":")
        async with MockTransferUnit(
            broker=host, port=int(port), publish_interval=0.1
        ) as unit:
            async with aiomqtt.Client(host, port=int(port)) as publisher:
                await publisher.publish(
                    "TransferUnit1/ConveyorBelt/right/speed_set", json.dumps(2.5).encode()
                )
                await unit.wait_for_setpoint()

            assert unit.speeds["right"] == 2.5
            assert unit.speeds["left"] == 0.0

    async def test_a_light_barrier_reports_occupancy(self, mqtt_broker):
        host, port = mqtt_broker.split(":")
        async with MockTransferUnit(
            broker=host, port=int(port), publish_interval=5.0
        ) as unit:
            await unit.set_occupied("front", True)

            received = await _collect(
                mqtt_broker, ["TransferUnit1/LightBarrier/front/occupied"], count=1
            )

        assert received[0][1] is True

    async def test_an_unparseable_setpoint_is_ignored_not_fatal(self, mqtt_broker):
        """A malformed payload from a device must not take the mock down."""
        host, port = mqtt_broker.split(":")
        async with MockTransferUnit(
            broker=host, port=int(port), publish_interval=0.1
        ) as unit:
            async with aiomqtt.Client(host, port=int(port)) as publisher:
                await publisher.publish(
                    "TransferUnit1/ConveyorBelt/left/speed_set", b"not-a-number"
                )
                await asyncio.sleep(0.3)
                await publisher.publish(
                    "TransferUnit1/ConveyorBelt/left/speed_set", json.dumps(3.0).encode()
                )
                await unit.wait_for_setpoint()

            assert unit.speeds["left"] == 3.0
