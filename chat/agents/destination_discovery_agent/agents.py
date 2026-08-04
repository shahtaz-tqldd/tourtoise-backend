import json

from google.adk.agents import Agent
from google.adk.tools.google_search_tool import GoogleSearchTool
from .tools import fetch_destination_items_tool
from .schema import (
    TripPreferenceQNAResponse,
    TripDestinationRecommendationsResponse,
)


class ADKAgent:
    def __init__(self):
        self.llm_model = "gemini-2.5-flash"

    def root_agent(self) -> Agent:
        
        return Agent(
            name="root_agent",
            model=self.llm_model,
            description="You are root agent that delegate task to the appropiate sub agent",
            instruction=f"""You are a root agent that delegate task to the sub agent""",
        )

    
    def destination_recommendation_agent(self):
        return Agent(
            name="root_agent",
            model=self.llm_model,
            description="You are root agent that delegate task to the appropiate sub agent",
            instruction=f"""You are a root agent that delegate task to the sub agent""",
        )