import litellm
from app.core.config import settings
from app.core.logger import logger
from app.models.schemas import Session, Topic, TopicKnowledge, Message
from typing import List, Dict, Tuple, Optional
import json

class AIEngine:
    def __init__(self):
        self.primary_model = settings.PRIMARY_MODEL_NAME
        self.secondary_model = settings.SECONDARY_MODEL_NAME

    def get_completion(self, messages: List[Dict], response_format: Optional[Dict] = None, model: Optional[str] = None) -> Optional[str]:
        target_model = model or self.primary_model
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                import time
                # Small protective delay to respect RPM
                time.sleep(0.5)
                
                response = litellm.completion(
                    model=target_model,
                    messages=messages,
                    response_format=response_format,
                    api_key=settings.GEMINI_API_KEY
                )
                
                # Log usage
                usage = getattr(response, 'usage', None)
                if usage:
                    prompt_tokens = getattr(usage, 'prompt_tokens', 0)
                    completion_tokens = getattr(usage, 'completion_tokens', 0)
                    total_tokens = getattr(usage, 'total_tokens', 0)
                    logger.info(
                        f"LLM Call Success: {target_model} | "
                        f"Input: {prompt_tokens} | Output: {completion_tokens} | Total: {total_tokens}"
                    )

                return response.choices[0].message.content

            except (litellm.ServiceUnavailableError, litellm.RateLimitError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Gemini busy/limited (Attempt {attempt + 1}). Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2 # Exponential backoff
                else:
                    logger.error(f"Gemini final failure after {max_retries} attempts: {e}")
                    return None
            except Exception as e:
                logger.error(f"Unexpected LiteLLM error: {e}")
                return None
        
        return None

    def get_embedding(self, text: str) -> List[float]:
        """
        Generates a vector embedding for the given text using LiteLLM.
        """
        try:
            response = litellm.embedding(
                model=settings.EMBEDDING_MODEL, 
                input=[text],
                api_key=settings.GEMINI_API_KEY
            )
            return response.data[0]['embedding']
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return [0.0] * settings.EMBEDDING_DIM # Return empty vector on error

    def interrogate(self, session: Session, chat_history: List[Message], current_topic: Topic) -> str:
        """
        Generates the next question or follow-up for the user based on the current context.
        """
        system_prompt = f"""
        You are a Senior Technical Architect conducting a Knowledge Transfer (KT) session.
        Your goal is to fully understand the system being explained by the user.
        
        Currently focusing on Topic: {current_topic.name}
        Current Knowledge for this topic: {current_topic.knowledge.model_dump_json(by_alias=True)}
        Missing Sections: {', '.join(current_topic.missing_sections)}
        
        Guidelines:
        1. Be professional, inquisitive, and structured.
        2. Ask targeted follow-up questions to fill in the 'Missing Sections'.
        3. Do NOT move to the next topic or generate a summary until you have at least 80% confidence in the current topic.
        4. Detect vague explanations and ask for specific details (e.g., specific error codes, exact CLI commands, or monitoring metrics).
        5. Never assume missing details; always clarify.
        6. If the user provided a lot of info, acknowledge it briefly and then ask the most critical missing detail.
        7. If this is the start, ask for a high-level overview first.
        """
        
        messages = [{"role": "system", "content": system_prompt}]
        for msg in chat_history[-10:]: # Pass last 10 messages for context
            messages.append({"role": msg.role, "content": msg.content})
            
        response = self.get_completion(messages, model=self.secondary_model)
        return response or "I'm having trouble thinking of the next question. Could you tell me more about the current topic?"

    def multi_topic_validate_and_score(self, session: Session, user_message: str) -> Dict[str, Dict]:
        """
        Analyzes the user message across all topics in the session.
        Returns a dictionary mapping topic_id to its updated validation results.
        """
        topics_json = {t.id: {"name": t.name, "current_knowledge": t.knowledge.model_dump()} for t in session.topics}
        
        prompt = f"""
        Analyze the following user input in the context of a KT session.
        The user might be providing information for multiple topics at once.
        
        User input: "{user_message}"
        
        Topics and their current knowledge:
        {json.dumps(topics_json, indent=2)}
        
        Task:
        1. For each topic, extract any new information provided in the user input.
        2. Update the knowledge state for each topic. 
        3. Rate the confidence score (0-100) for each topic based on total knowledge gathered.
        4. Identify which sections are still missing or vague for each topic.
        
        Return the result as a JSON object where keys are Topic IDs (e.g., "t1", "t2"):
        {{
            "t1": {{
                "knowledge": {{ ... }},
                "confidence_score": integer,
                "missing_sections": ["list"]
            }},
            ...
        }}
        """
        
        messages = [
            {"role": "system", "content": "You are a specialized system analyzer. Always return JSON mapping topic IDs to their updates."},
            {"role": "user", "content": prompt}
        ]
        
        response_str = self.get_completion(messages, response_format={"type": "json_object"}, model=self.primary_model)
        if not response_str:
            return {}
            
        try:
            return json.loads(response_str)
        except Exception as e:
            logger.error(f"Error parsing multi-topic validation JSON: {e}")
            return {}

    def validate_and_score(self, current_topic: Topic, user_message: str) -> Tuple[TopicKnowledge, int, List[str]]:
        """
        [Legacy Wrapper] Parses the user message to extract knowledge for a single topic.
        """
        # Create a dummy session with just this topic to reuse the multi-topic logic
        temp_session = Session(id="temp", topics=[current_topic])
        results = self.multi_topic_validate_and_score(temp_session, user_message)
        
        if current_topic.id in results:
            data = results[current_topic.id]
            knowledge = TopicKnowledge(**data.get("knowledge", {}))
            score = data.get("confidence_score", 0)
            missing = data.get("missing_sections", [])
            return knowledge, score, missing
        
        return current_topic.knowledge, current_topic.confidence_score, current_topic.missing_sections

    def generate_final_summary(self, session: Session) -> str:
        """
        Generates a professional, structured KT document once all topics are complete.
        """
        system_prompt = """
        You are a Senior Technical Architect. Generate a production-ready, structured KT document.
        Use the provided session data which includes multiple topics with detailed knowledge.
        
        The document must include:
        - Executive Overview
        - System Architecture
        - Module Breakdown (for each topic)
        - Data Flow (Inputs/Outputs) - **MANDATORY: Use Markdown tables for this section**
        - Dependencies
        - Failure & Recovery Strategy (from failure cases/edge cases)
        - Monitoring & Operations
        - Deployment
        - Risks
        - Operational Checklist - **MANDATORY: Use a Markdown table or highly structured task list**
        
        Formatting Guidelines:
        1. Use clean GitHub Flavored Markdown (GFM).
        2. Use Markdown headers: # for the title, ## for major sections, and ### for subsections.
        3. DO NOT use HTML tags (like <h1>, <div>, <br>). ONLY use Markdown syntax.
        4. Use bold text for emphasis.
        5. Ensure all tables have proper headers and look professional.
        6. Maintain a professional, technical tone throughout.
        """
        
        # Prepare context
        context = ""
        for topic in session.topics:
            context += f"\n--- Topic: {topic.name} ---\n{topic.knowledge.model_dump_json(by_alias=True)}\n"
            
        messages = [
            {"role": "system", "content": system_prompt + "\nIMPORTANT: Do not include the Session ID or any internal technical identifiers in the final report."},
            {"role": "user", "content": f"Generate the final summary for this session data:\n{context}"}
        ]
        
        response = self.get_completion(messages, model=self.primary_model)
        return response or "Error: Could not generate the final summary due to model unavailability. Please try again in 5 minutes."

ai_engine = AIEngine()
