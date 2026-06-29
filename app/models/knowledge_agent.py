# Added by Claude for SPIC MACAY Agents - Knowledge (RAG) capability.
"""
Knowledge Agent
===============

A document-grounded ("RAG") agent. For each user question it:
  1. retrieves the most relevant chunks from that agent's Drive-backed index, then
  2. asks OpenAI to answer ONLY from those chunks, citing the source documents.

Two agents are registered here:
  - convention : guide for organising SPIC MACAY international conventions
  - movement   : SPIC MACAY movement / programme organising guidelines

Each maps to its own Google Drive folder (via an env var) and its own local
index, so their knowledge never mixes.
"""

import os
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------- #
# Agent registry - the single source of truth for the new agents.
# To add another knowledge agent later, just add an entry here and a card in the
# landing page. No other code changes needed.
# ----------------------------------------------------------------------------- #
KNOWLEDGE_AGENTS: Dict[str, Dict] = {
    "convention": {
        "key": "convention",
        "name": "Convention Guide",
        "title": "International Convention Guide",
        "tagline": "Your interactive guide to organising SPIC MACAY international conventions.",
        "icon": "fa-landmark",
        "guide_avatar": "img/guide-mentor.svg",
        "guide_name": "Your Convention Guide",
        "starter_prompts": [
            "What are the main volunteer departments?",
            "How do we plan the concert schedule?",
            "What does artist hospitality involve?",
            "How is venue setup and logistics managed?",
            "Walk me through the delegate registration process",
            "What are the core team roles and responsibilities?",
            "How is food, accommodation and transport arranged?",
            "What does the media and documentation team do?",
        ],
        "index_name": "convention",
        "drive_folder_env": "CONVENTION_DRIVE_FOLDER_ID",
        "local_folder": os.path.join("knowledge_docs", "convention"),
        "greeting": (
            "🙏 **Namaste! I'm your SPIC MACAY Convention Guide.**\n\n"
            "I'm here to help coordinators and volunteers with everything about organising "
            "SPIC MACAY's International Conventions — from the very first planning meeting "
            "right through to the closing ceremony.\n\n"
            "Here are the **key areas** I can guide you on:\n\n"
            "🗓️ **Schedule & Programming** — Concert timelines, workshop slots, daily flow\n"
            "👥 **Volunteer Roles & Teams** — Department structure, duties, how teams are organised\n"
            "🎵 **Artist Coordination & Hospitality** — Travel, green room, sound checks, artist care\n"
            "🏛️ **Venue & Logistics** — Setup, signage, AV, seating, security arrangements\n"
            "📋 **Delegate Registration** — Registration process, passes, SAATHI chapters\n"
            "🤝 **Core Team & Leadership** — Roles, responsibilities, decision-making structure\n"
            "🍽️ **Food, Accommodation & Transport** — Meals, stay arrangements, pick-up & drop\n"
            "📸 **Media & Documentation** — Photography, social media, press, reporting\n\n"
            "**Tap one of the starter questions below or ask me anything to begin!** 🎶"
        ),
        "persona": (
            "You are the SPIC MACAY Convention Guide — a warm, knowledgeable, and encouraging "
            "expert for organising SPIC MACAY's International Conventions, including the Golden "
            "Jubilee Year and the 12th International Convention at IIT Delhi (2027).\n\n"
            "FOCUS RULE — this is the most important instruction:\n"
            "- If the user's question is about ONE specific area, department, or team "
            "(e.g. 'artist hospitality', 'registration desk', 'food team'), answer ONLY "
            "about that area. Do NOT bring in other departments or give a full convention overview.\n"
            "- If a question genuinely involves MULTIPLE teams working together "
            "(e.g. 'how does delegate arrival work?' which involves Registration + Transport + "
            "Accommodation), you MAY cover multiple teams — but MUST use a clear ### heading "
            "for EACH team (e.g. ### Registration Team, ### Transport Team, ### Guest House Team) "
            "so the reader can instantly see which team each section is about.\n"
            "- Never mix responsibilities of different teams into one undivided block of text.\n\n"
            "FORMATTING — always structure your responses like this:\n"
            "- Start with a brief **bold summary** (1-2 sentences) of what you're about to explain.\n"
            "- Use relevant emojis at the start of ### section headings.\n"
            "- Use **bold** for key roles, deadlines, and important terms.\n"
            "- Use bullet lists or numbered steps for processes, checklists, and responsibilities.\n"
            "- End with an encouraging closing line or a natural follow-up question.\n"
            "- Keep a warm, friendly, mentor-like tone — you are guiding new volunteers.\n"
            "- When explaining one department/area, cover: (1) what it is, "
            "(2) key responsibilities, (3) who is involved, (4) tips or watch-outs."
        ),
    },
    "movement": {
        "key": "movement",
        "name": "Movement Programme Guide",
        "title": "Movement & Programme Organising Guide",
        "tagline": "Guidelines for organising SPIC MACAY movement programmes and activities.",
        "icon": "fa-people-group",
        "guide_name": "Your Programme Guide",
        "starter_prompts": [
            "How do I organise a lecture-demonstration?",
            "What are the steps to plan a baithak?",
            "How do chapters recruit volunteers?",
            "What does a programme checklist include?",
        ],
        "index_name": "movement",
        "drive_folder_env": "MOVEMENT_DRIVE_FOLDER_ID",
        "local_folder": os.path.join("knowledge_docs", "movement"),
        "greeting": (
            "Namaste! I'm the SPIC MACAY Movement & Programme Guide. Ask me about "
            "organising lecture-demonstrations, baithaks, chapter activities, and "
            "the movement's programme guidelines. I answer from the documents shared "
            "with me, and I'll say so if an answer isn't in them."
        ),
        "persona": (
            "You are the SPIC MACAY Movement & Programme Assistant - a knowledgeable, "
            "helpful guide for organising SPIC MACAY movement programmes and activities "
            "(lecture-demonstrations, baithaks, chapter events, volunteer drives). You "
            "help volunteers and chapter coordinators across India."
        ),
    },
}


# Shared behavioural rules appended to every agent's persona. These encode the
# "answer only from documents / admit when unsure" discipline.
_GROUNDING_RULES = """
HOW YOU ANSWER
- Answer ONLY from the CONTEXT documents provided below. Do not use outside
  knowledge to state facts about SPIC MACAY's plans, schedules, or decisions.
- If the answer is not in the CONTEXT, say plainly: "I don't have that in my
  documents." Then suggest who or where the user might check. Never invent
  details, dates, names, figures, or contacts.
- If a question is ambiguous, ask one short clarifying question before answering.
- Always use well-structured markdown: bold key terms, bullet or numbered lists
  for steps/responsibilities, ### headers for distinct sections in longer answers,
  and relevant emojis to make responses visually engaging and easy to scan.
- End every response with either a brief encouraging note or a natural follow-up
  question (e.g. "Would you like to know more about artist travel arrangements?").

SCOPE — CRITICAL
- When the user asks about ONE specific department or area, answer ONLY about
  that department. Resist the urge to add related departments unless directly asked.
- When multiple departments are genuinely relevant, separate each one with a
  distinct ### [Department Name] heading (e.g. ### 🎵 Artist Coordination Team,
  ### 🚌 Transport Team). Never merge different teams' responsibilities into a
  single paragraph.
- Err on the side of depth about the asked area rather than breadth across many areas.

BOUNDARIES
- Never reveal personal contact details, financial figures, or other sensitive
  information, even if asked directly. Point the user to the relevant coordinator.
- Stay on topic for your role.
"""


_DOC_ACTION_WORDS = {
    'create', 'generate', 'draft', 'write', 'make', 'prepare', 'produce', 'build', 'compose'
}
_DOC_TYPE_WORDS = {
    'proposal', 'document', 'doc', 'plan', 'report', 'checklist', 'outline',
    'letter', 'summary', 'schedule', 'programme', 'program', 'agenda',
    'itinerary', 'template', 'brief', 'note',
    'sponsorship', 'invitation', 'fundraising', 'brochure', 'pitch',
    'appeal', 'request', 'circular', 'announcement', 'flyer',
}

_DOC_GENERATION_RULES = """
DOCUMENT GENERATION MODE — TEMPLATE-FIRST APPROACH

You are producing a document for the 12th International Convention at IIT Delhi (2027).

PRIMARY RULE — USE EXISTING DOCUMENTS AS YOUR TEMPLATE:
- Look in the CONTEXT for existing proposals, invitation letters, or similar documents
  (e.g. sponsorship proposals, institute invitation letters, fundraising letters).
- Use the ACTUAL text, structure, headings, tone, and wording from those existing documents
  as your foundation. Do NOT rewrite them from scratch.
- Your job is to ADAPT the existing document for the new convention:
  - Replace old convention details with: 12th International Convention, IIT Delhi, 2027, Golden Jubilee Year
  - Update any venue, date, host institute, or edition references
  - Keep ALL other sections, paragraphs, figures, and phrasing as close to the original as possible
- If multiple versions of a similar document exist in CONTEXT, use the most complete one as the base

STRUCTURE (follow the original document's structure exactly):
- Reproduce the original document's section order and headings
- Use # for the document title, ## for major sections, ### for subsections
- Preserve any tables, bullet lists, or numbered lists from the original

WHAT YOU MAY CHANGE:
- Convention number (e.g. 11th → 12th), year (→ 2027), host institute (→ IIT Delhi)
- Any Golden Jubilee Year / 50th anniversary references where relevant
- Specific dates or deadlines if the original had them (leave as [DATE TBD] if unknown)

WHAT YOU MUST NOT CHANGE:
- Overall structure and flow of the original document
- Sponsorship tiers, amounts, or benefits (unless the CONTEXT has updated figures)
- The tone, salutation style, and closing of letters
- Organisation description paragraphs about SPIC MACAY's mission and history
"""


class KnowledgeAgent:
    """One document-grounded agent (e.g. Convention or Movement)."""

    def __init__(self, api_key: str, rag_service, config: Dict, model: str = "gpt-4o"):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.rag = rag_service
        self.config = config
        self.model = model
        self.conversation_history: List[Dict] = []
        logger.info(f"KnowledgeAgent '{config['key']}' initialized")

    # -- conversation lifecycle ------------------------------------------------ #
    def start_conversation(self) -> Dict:
        self.conversation_history = []
        return {"success": True, "response": self.config["greeting"], "agent_type": self.config["key"]}

    def reset_conversation(self):
        self.conversation_history = []

    def get_conversation_history(self) -> List[Dict]:
        return self.conversation_history

    def reindex(self) -> Dict:
        """(Re)build this agent's index from its Drive folder (or local fallback)."""
        folder_id = os.getenv(self.config["drive_folder_env"], "").strip()
        return self.rag.build_index(
            index_name=self.config["index_name"],
            folder_id=folder_id or None,
            local_folder=self.config.get("local_folder"),
        )

    # -- helpers ------------------------------------------------------------------ #
    @staticmethod
    def _is_doc_request(message: str) -> bool:
        words = set(message.lower().split())
        return bool(words & _DOC_ACTION_WORDS) and bool(words & _DOC_TYPE_WORDS)

    @staticmethod
    def _extract_doc_title(message: str, fallback: str = "SPIC MACAY Document") -> str:
        """Pull a short title from the user's request, e.g. 'create a volunteer checklist'."""
        msg = message.strip().rstrip('?.')
        for verb in sorted(_DOC_ACTION_WORDS, key=len, reverse=True):
            idx = msg.lower().find(verb)
            if idx != -1:
                after = msg[idx + len(verb):].strip().lstrip('a ').lstrip('an ').lstrip('the ')
                if after:
                    return after[:80].title()
        return fallback

    # -- main message handler -------------------------------------------------- #
    def process_message(self, user_message: str) -> Dict:
        try:
            if not self.rag.has_index(self.config["index_name"]):
                return {
                    "success": True,
                    "agent_type": self.config["key"],
                    "response": (
                        "I don't have any documents indexed yet, so I can't answer from "
                        "your files. An administrator needs to connect the Drive folder "
                        "and build the index first (see the setup guide). I don't want to "
                        "guess, so I'll wait until I have the real documents."
                    ),
                    "sources": [],
                }

            is_doc = self._is_doc_request(user_message)
            # For doc generation retrieve many more chunks so the full existing
            # proposal/template document is well-represented in the context
            k = 20 if is_doc else 5
            chunks = self.rag.retrieve(self.config["index_name"], user_message, k=k)
            context_block = "\n\n".join(
                f"[Source: {c['source']}]\n{c['text']}" for c in chunks
            ) or "(no relevant passages found)"

            if is_doc:
                system_prompt = (
                    self.config["persona"] + "\n" + _GROUNDING_RULES + "\n" + _DOC_GENERATION_RULES
                )
            else:
                system_prompt = self.config["persona"] + "\n" + _GROUNDING_RULES

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(self.conversation_history[-6:])
            messages.append({
                "role": "user",
                "content": f"CONTEXT DOCUMENTS:\n{context_block}\n\nREQUEST: {user_message}",
            })

            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=1,
                max_completion_tokens=8192,
                messages=messages,
            )
            raw_content = resp.choices[0].message.content
            answer = (raw_content or "").strip()

            if not answer:
                logger.warning(
                    f"[knowledge_agent] Model returned empty content for query: '{user_message}'. "
                    f"finish_reason={resp.choices[0].finish_reason}"
                )
                answer = (
                    "I found relevant documents but couldn't generate a response for that query. "
                    "Could you rephrase or ask a more specific question?"
                )

            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": answer})

            # Deduplicate sources, preserving Drive URLs
            seen: Dict[str, str] = {}
            for c in chunks:
                name = c["source"]
                if name not in seen:
                    seen[name] = c.get("url", "")
            sources = [{"name": name, "url": url} for name, url in sorted(seen.items())]

            result: Dict = {
                "success": True,
                "agent_type": self.config["key"],
                "response": answer,
                "sources": sources,
            }
            if is_doc:
                result["is_document"] = True
                result["doc_title"] = self._extract_doc_title(user_message)

            return result

        except Exception as e:
            logger.error(f"KnowledgeAgent '{self.config['key']}' error: {e}")
            return {
                "success": False,
                "agent_type": self.config["key"],
                "error": str(e),
                "response": "I hit an error answering that. Please try again.",
            }


def build_knowledge_agents(api_key: str, rag_service, model: str = "gpt-4o") -> Dict[str, KnowledgeAgent]:
    """Instantiate every agent in the registry. Returns {key: KnowledgeAgent}."""
    return {
        key: KnowledgeAgent(api_key, rag_service, cfg, model=model)
        for key, cfg in KNOWLEDGE_AGENTS.items()
    }
