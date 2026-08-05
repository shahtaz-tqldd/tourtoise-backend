import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import User
from chat.agents.discovery_agent.client import DiscoveryAgentClient
from chat.agents.discovery_agent.helpers import _parse_response
from chat.api.v1.client.views import ChatQuestionAPIView
from chat.choices import ChatMessageSender
from chat.models import ChatMessage, ChatSession


class DiscoveryResponseParsingTests(SimpleTestCase):
    def test_parses_typed_response(self):
        raw = json.dumps(
            {
                "message": "Bali is a good fit.",
                "intention": "destination_recommendation",
                "destinations": [
                    {
                        "destination_id": "destination-1",
                        "name": "Bali",
                        "country": "Indonesia",
                        "why_it_matches": "It combines beaches and food.",
                    }
                ],
                "handoff": None,
            }
        )

        parsed = _parse_response(raw)

        self.assertEqual(parsed["intention"], "destination_recommendation")
        self.assertEqual(parsed["destinations"][0]["name"], "Bali")

    def test_rejects_unknown_intention(self):
        raw = json.dumps(
            {
                "message": "Hello",
                "intention": "unknown",
                "destinations": [],
                "handoff": None,
            }
        )

        self.assertIsNone(_parse_response(raw))


class DiscoveryAgentClientTests(SimpleTestCase):
    def test_returns_stable_fallback_when_not_initialized(self):
        client = DiscoveryAgentClient.__new__(DiscoveryAgentClient)
        client.session_service = None
        client.app = None

        result = self.async_run(client)

        self.assertTrue(result["meta"]["fallback"])
        self.assertEqual(result["response"]["destinations"], [])

    @staticmethod
    def async_run(client):
        from asgiref.sync import async_to_sync

        return async_to_sync(client.run_agent)(
            user_query="Where should I go?",
            user_id="user-1",
        )


class ChatQuestionAPIViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveller@example.com", password="pass")
        self.factory = APIRequestFactory()

    @patch("chat.api.v1.client.views.DiscoveryAgentClient")
    def test_persists_agent_response_and_external_session(self, client_class):
        async def run_agent(**kwargs):
            return {
                "session_id": "adk-session-1",
                "response": {
                    "message": "Try Kyoto for food and culture.",
                    "intention": "destination_recommendation",
                    "destinations": [{"destination_id": "destination-1"}],
                    "handoff": None,
                },
                "meta": {
                    "query_intention": "destination_recommendation",
                    "token_usage": 12,
                    "cost": 0.001,
                    "time": 0.2,
                    "fallback": False,
                },
            }

        client_class.return_value.run_agent = run_agent
        request = self.factory.post("/chat/ask/", {"message": "Food and culture"})
        force_authenticate(request, user=self.user)

        response = ChatQuestionAPIView.as_view()(request)

        self.assertEqual(response.status_code, 201)
        session = ChatSession.objects.get(user=self.user)
        self.assertEqual(session.metadata["discovery_agent_session_id"], "adk-session-1")
        self.assertEqual(
            list(session.messages.values_list("sender", flat=True)),
            [ChatMessageSender.USER, ChatMessageSender.AGENT],
        )
        agent_message = ChatMessage.objects.get(
            session=session, sender=ChatMessageSender.AGENT
        )
        self.assertEqual(agent_message.content, "Try Kyoto for food and culture.")
        self.assertEqual(
            agent_message.metadata["query_intention"], "destination_recommendation"
        )
