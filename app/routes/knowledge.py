# Added by Claude for SPIC MACAY Agents - Knowledge (RAG) capability.
"""
Knowledge Agent API routes.

Endpoints (registered under /api/knowledge):
  GET  /agents                  -> list available knowledge agents (for the UI cards)
  POST /<agent_key>/start       -> greeting for that agent
  POST /<agent_key>/chat        -> ask a question (RAG-grounded answer)
  POST /<agent_key>/reset       -> clear that agent's conversation
  POST /<agent_key>/reindex     -> (re)build the agent's index from Drive/local docs
"""
from flask import Blueprint, request, jsonify, current_app, Response
import logging
import re

logger = logging.getLogger(__name__)
knowledge_bp = Blueprint("knowledge", __name__)


def _get_agent(agent_key):
    agents = getattr(current_app, "knowledge_agents", {})
    return agents.get(agent_key)


@knowledge_bp.route("/agents", methods=["GET"])
def list_agents():
    from app.models.knowledge_agent import KNOWLEDGE_AGENTS
    public = [
        {
            "key": c["key"], "name": c["name"], "title": c["title"],
            "tagline": c["tagline"], "icon": c["icon"],
        }
        for c in KNOWLEDGE_AGENTS.values()
    ]
    return jsonify({"success": True, "agents": public})


@knowledge_bp.route("/<agent_key>/start", methods=["POST"])
def start(agent_key):
    agent = _get_agent(agent_key)
    if not agent:
        return jsonify({"success": False, "error": f"Unknown agent '{agent_key}'"}), 404
    return jsonify(agent.start_conversation())


@knowledge_bp.route("/<agent_key>/chat", methods=["POST"])
def chat(agent_key):
    agent = _get_agent(agent_key)
    if not agent:
        return jsonify({"success": False, "error": f"Unknown agent '{agent_key}'"}), 404
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400
    return jsonify(agent.process_message(message))


@knowledge_bp.route("/<agent_key>/reset", methods=["POST"])
def reset(agent_key):
    agent = _get_agent(agent_key)
    if not agent:
        return jsonify({"success": False, "error": f"Unknown agent '{agent_key}'"}), 404
    agent.reset_conversation()
    return jsonify({"success": True, "message": "Conversation reset"})


@knowledge_bp.route("/<agent_key>/reindex", methods=["POST"])
def reindex(agent_key):
    """Rebuild the document index. Run this after adding/updating Drive docs."""
    agent = _get_agent(agent_key)
    if not agent:
        return jsonify({"success": False, "error": f"Unknown agent '{agent_key}'"}), 404
    try:
        result = agent.reindex()
        code = 200 if result.get("success") else 400
        return jsonify(result), code
    except Exception as e:
        logger.error(f"Reindex failed for '{agent_key}': {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@knowledge_bp.route("/<agent_key>/download-doc", methods=["POST"])
def download_doc(agent_key):
    """
    Generate and stream a Word or PDF document from provided markdown content.

    Body JSON:
        title   (str)  : document title / filename
        content (str)  : markdown body
        format  (str)  : "docx" (default) or "pdf"
    """
    from app.services.doc_generator import generate_docx, generate_pdf

    data = request.get_json(silent=True) or {}
    title   = (data.get("title")   or "SPIC MACAY Document").strip()
    content = (data.get("content") or "").strip()
    fmt     = (data.get("format")  or "docx").lower()

    if not content:
        return jsonify({"success": False, "error": "No content provided"}), 400

    # Safe filename
    safe_name = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:60]

    if fmt == "pdf":
        data_bytes = generate_pdf(title, content)
        if not data_bytes:
            return jsonify({"success": False, "error": "PDF generation failed"}), 500
        return Response(
            data_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'}
        )
    else:
        data_bytes = generate_docx(title, content)
        if not data_bytes:
            return jsonify({"success": False, "error": "Word generation failed"}), 500
        return Response(
            data_bytes,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.docx"'}
        )
