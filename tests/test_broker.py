"""메시지 브로커 기본 동작."""

from mas.messaging.broker import MessageBroker, Topic
from mas.messaging.message import AgentMessage, Intent


def test_broker_register_publish():
    b = MessageBroker()

    class A:
        agent_id = "EA"
        def receive_message(self, m):
            pass

    agent = A()
    b.register(agent)
    msg = AgentMessage.create("QA", "EA", Intent.ALERT, {"summary": "t"})
    env = b.publish(msg, topic=Topic.ALERTS)
    assert env.message.header.sender == "QA"
    assert b.metrics.total_published >= 1
