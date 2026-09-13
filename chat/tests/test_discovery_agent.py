import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.models import User
from analytics.choices import AIUsageType
from analytics.models import AIUsage
from chat.agents.discovery_agent.agents import DiscoveryADKAgent
from chat.agents.discovery_agent.client import DiscoveryAgentClient
from chat.agents.discovery_agent.helpers import _parse_response
from chat.api.v1.client.serializers import ChatMessageSerializer
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
                        "destination_slug": "bali-indonesia",
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
        self.assertEqual(
            parsed["destinations"][0]["destination_slug"],
            "bali-indonesia",
        )
        self.assertNotIn("destination_id", parsed["destinations"][0])

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

    def test_parses_handoff_with_start_and_end_dates(self):
        raw = json.dumps(
            {
                "message": "Let's start planning Kyoto.",
                "intention": "start_trip_planning",
                "destinations": [],
                "handoff": {
                    "destination_slug": "kyoto-japan",
                    "start_date": "2026-10-05",
                    "end_date": "2026-10-09",
                    "source_session_id": "chat-session-1",
                },
            }
        )

        parsed = _parse_response(raw)

        self.assertEqual(parsed["handoff"]["start_date"], "2026-10-05")
        self.assertEqual(parsed["handoff"]["end_date"], "2026-10-09")
        self.assertEqual(parsed["handoff"]["destination_slug"], "kyoto-japan")
        self.assertNotIn("destination_id", parsed["handoff"])

    def test_parses_handoff_with_start_date_and_duration(self):
        raw = json.dumps(
            {
                "message": "Let's start planning Kyoto.",
                "intention": "start_trip_planning",
                "destinations": [],
                "handoff": {
                    "destination_slug": "kyoto-japan",
                    "start_date": "2026-10-05",
                    "duration_days": 5,
                    "source_session_id": "chat-session-1",
                },
            }
        )

        parsed = _parse_response(raw)

        self.assertEqual(parsed["handoff"]["start_date"], "2026-10-05")
        self.assertEqual(parsed["handoff"]["duration_days"], 5)

    def test_rejects_handoff_without_duration_or_end_date(self):
        raw = json.dumps(
            {
                "message": "Let's start planning Kyoto.",
                "intention": "start_trip_planning",
                "destinations": [],
                "handoff": {
                    "destination_slug": "kyoto-japan",
                    "start_date": "2026-10-05",
                    "source_session_id": "chat-session-1",
                },
            }
        )

        self.assertIsNone(_parse_response(raw))


class DiscoveryAgentInstructionTests(SimpleTestCase):
    def test_planning_handoff_resolves_casual_schedule(self):
        instruction = DiscoveryADKAgent(
            user=None,
            source_session_id="chat-session-1",
            current_date=date(2026, 8, 18),
        )._instruction()

        self.assertIn("2026-08-18", instruction)
        self.assertIn("Tuesday", instruction)
        self.assertIn('casual scheduling language such as "next Sunday"', instruction)
        self.assertIn("first occurrence", instruction)
        self.assertIn("Never ask the traveller to convert", instruction)
        self.assertIn("min_stay_days", instruction)
        self.assertIn("Never ask the traveller to choose between the bounds", instruction)
        self.assertIn("recommendation's destination_slug", instruction)
        self.assertIn("Do not put destination IDs in recommendation output", instruction)
        self.assertIn("handoff.destination_slug", instruction)
        self.assertIn("Do not put the destination ID in the handoff", instruction)


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


class ChatMessageSerializerTests(SimpleTestCase):
    def test_hides_cost_and_token_usage_from_metadata(self):
        message = ChatMessage(
            sender=ChatMessageSender.AGENT,
            content="Try Kyoto.",
            metadata={
                "query_intention": "destination_recommendation",
                "cost": 0.001,
                "token_usage": 12,
                "time": 0.2,
            },
        )

        data = ChatMessageSerializer(message).data

        self.assertEqual(
            data["metadata"],
            {
                "query_intention": "destination_recommendation",
                "time": 0.2,
            },
        )
        self.assertIn("cost", message.metadata)
        self.assertIn("token_usage", message.metadata)


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
                    "destinations": [{"destination_slug": "kyoto-japan"}],
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
        self.assertEqual(response.data["meta"]["credit_spent"], 2)
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
        self.user.credit.refresh_from_db()
        self.assertEqual(self.user.credit.balance, 98)
        usage = AIUsage.objects.get(user=self.user)
        self.assertEqual(usage.usage_type, AIUsageType.CHAT)
        self.assertEqual(usage.cost, Decimal("0.00100000"))
        self.assertEqual(usage.tokens, 12)
        self.assertIsNone(usage.trip)
        self.assertEqual(usage.metadata, {})

    @patch("chat.api.v1.client.views.DiscoveryAgentClient")
    def test_rejects_question_without_enough_credits(self, client_class):
        self.user.credit.balance = 1
        self.user.credit.save(update_fields=["balance"])
        request = self.factory.post("/chat/ask/", {"message": "Food and culture"})
        force_authenticate(request, user=self.user)

        response = ChatQuestionAPIView.as_view()(request)

        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data["message"], "Insufficient credits.")
        self.assertFalse(ChatSession.objects.filter(user=self.user).exists())
        self.assertFalse(AIUsage.objects.filter(user=self.user).exists())
        client_class.assert_not_called()
