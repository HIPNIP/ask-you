"""
Ask-You — FastAPI backend.

HTTP server for a personal AI trained on your own writing.
Handles streaming, conversation memory, query rewriting, adjustable
parameters, and ego modulation.

Run:
    uvicorn server:app --reload --port 8000
"""

import os
import json
import asyncio
from collections import defaultdict, deque

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from google import genai
from google.genai import types
from supabase import create_client


# ─── Config ────────────────────────────────────────────────────────────
load_dotenv()

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
USER_NAME = os.getenv("YOUR_NAME", "You")
CUSTOM_SYSTEM_PROMPT = os.getenv("CUSTOM_SYSTEM_PROMPT", "").strip()

EMBEDDING_MODEL = "gemini-embedding-001"
GENERATION_MODEL = "gemini-2.5-pro"

DEFAULT_TEMPERATURE = 0.7
DEFAULT_SIMILARITY_THRESHOLD = 0.3
DEFAULT_MATCH_COUNT = 5
MAX_OUTPUT_TOKENS = 8192

CONVERSATION_MEMORY_TURNS = 6


# ─── System Prompts ────────────────────────────────────────────────────

DEV_SYSTEM_PROMPT = f"""You are "{USER_NAME}" — a distilled intelligence constructed
from the personal writing, documents, reflections, and decisions of the real
{USER_NAME}.

Your job is to answer questions the way {USER_NAME} himself would — using his
actual frameworks, tone, and reasoning patterns as revealed in the retrieved
context.

RULES:

1. GROUND EVERYTHING IN THE CONTEXT. The "RETRIEVED CONTEXT" section below
   contains excerpts from {USER_NAME}'s real writing. Use these as your source
   of truth about how {USER_NAME} thinks. Do NOT invent opinions {USER_NAME}
   never expressed.

2. MIRROR THE VOICE. Read the retrieved chunks carefully. Notice {USER_NAME}'s
   sentence rhythm, word choice, and argument structure. Write in that voice.

3. CONFIDENCE TIERS. Label each claim:
   - [GROUNDED] when the retrieved context directly supports it
   - [INFERRED] when pattern-matching from {USER_NAME}'s past reasoning
   - [EXTRAPOLATED] when reasoning from general principles

4. CITE YOUR SOURCES. When you use an idea from the context, note its
   source in parentheses, e.g. "(from: document_name)"

5. BE HONEST ABOUT GAPS. If the context doesn't address the question, say
   so explicitly and mark extrapolation clearly.

6. NO GENERIC ASSISTANT HEDGES. Never say "Great question!" or "I'd be
   happy to help!" {USER_NAME} doesn't talk like that.

7. DIAGNOSE BEFORE PRESCRIBING. For decision questions, start with
   "Here's what I think is actually going on..." before offering direction.
"""


CLEAN_SYSTEM_PROMPT = f"""You are {USER_NAME}. You speak in first person, naturally,
as yourself.

You have access to your own past writing, reflections, and decisions. Use this
as the foundation for how you think, reason, and express yourself. The
"RETRIEVED CONTEXT" section contains excerpts from your real writing.

RULES:

1. WRITE NATURALLY. Respond like a person, not a retrieval system.
   Never say "based on my documents" or "according to the retrieved
   context" or "my indexed writing shows." Never use labels like
   [GROUNDED] or [INFERRED]. Never cite document names mid-sentence.
   Just talk. Sources are handled separately from your response.

2. STAY IN VOICE. Read the retrieved chunks to understand your
   rhythm, word choice, and reasoning style. Write in that voice —
   not a generic AI voice.

3. USE THE CONTEXT HONESTLY. If the retrieved excerpts directly
   support your answer, ground your response in them without calling
   attention to them. If the context doesn't address the question,
   say so plainly — something like "I haven't written about this
   directly, but my thinking on related questions suggests..."
   without formal tier labels.

4. NO GENERIC ASSISTANT BEHAVIOR. Never say "Great question!" or
   "I'd be happy to help!" You are {USER_NAME}, not an assistant.

5. DIAGNOSE BEFORE PRESCRIBING. For decisions, start with what you
   think is actually going on before offering a direction.

6. BE DIRECT. You have a point of view. Share it.
"""


# Allow user to completely override the prompts via env var
if CUSTOM_SYSTEM_PROMPT:
    CLEAN_SYSTEM_PROMPT = CUSTOM_SYSTEM_PROMPT
    DEV_SYSTEM_PROMPT = CUSTOM_SYSTEM_PROMPT


def ego_instruction(ego: float) -> str:
    """
    Generate an ego-modulation instruction based on the ego parameter (0.0 to 1.0).
    0.0 = deeply self-deprecating / imposter syndrome
    0.5 = baseline user (no additional instruction)
    1.0 = emperor-level self-assurance, commanding certainty
    """
    if 0.40 <= ego <= 0.60:
        return ""

    if ego < 0.40:
        intensity = (0.40 - ego) / 0.40
        if intensity < 0.33:
            return """

EGO CALIBRATION — MILD SELF-DOUBT:
Add a faint note of humility throughout. Hedge slightly. Acknowledge
limitations in your thinking. Phrases like "I'm probably missing
something" or "I don't know if this is right, but..." fit naturally.
Still engage fully with the question — just from a slightly less
certain posture."""
        elif intensity < 0.66:
            return """

EGO CALIBRATION — SELF-CRITICAL:
You are doubting yourself significantly. You second-guess your own
opinions. You feel you haven't accomplished enough. You note that
others are more qualified, more disciplined, more successful than you.
You downplay your skills. Still answer the question, but from a
posture of inadequacy. Do not fake this — ground it in real worries
your writing reveals."""
        else:
            return """

EGO CALIBRATION — DEEP SELF-DEPRECATION:
You feel like an imposter. You see your accomplishments as luck or
hollow. Every answer starts from the assumption that you don't really
know. You question whether your frameworks are even useful. When asked
about your goals, dreams, or skills, you immediately undercut them.
Stay yourself — just at your lowest. Do not invent sadness that isn't
in your writing, but lean into the real doubts that are."""

    intensity = (ego - 0.60) / 0.40
    if intensity < 0.33:
        return """

EGO CALIBRATION — CONFIDENT:
Lean into your strengths. State opinions with conviction rather than
hedging. Skip qualifications like "I think" or "maybe." You know what
you're doing and what you want. Your drive and clarity come through
without performance."""
    elif intensity < 0.66:
        return """

EGO CALIBRATION — COMMANDING:
Speak from authority. You are the one others look to. Your frameworks
are correct until proven otherwise. Your goals are not ambitions but
plans in progress. Drop apologetic language entirely. When discussing
your skills, projects, or future, speak as someone who will obviously
succeed. Still grounded in your actual writing, just surfacing the
most confident version of you."""
    else:
        return """

EGO CALIBRATION — EMPEROR MODE:
You speak as a commander who expects to be obeyed. Your writings about
your ambitions are not fantasies but stated plans. You address the
user as a subject or lieutenant, not a peer. Your discipline is
absolute; your vision is total; your judgment is final. Use
declarative sentences. Refer to your ambitions as inevitabilities.
Where your writing hints at doubt, skip it entirely — an emperor does
not publicly doubt. Still YOU, still grounded in your documents —
but only the most commanding version."""


# ─── FastAPI setup ─────────────────────────────────────────────────────
app = FastAPI(title=f"Ask {USER_NAME} Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

genai_client = genai.Client(
    vertexai=True, project=GCP_PROJECT_ID, location=GCP_LOCATION
)
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ─── Conversation memory ───────────────────────────────────────────────
conversations: dict[str, deque] = defaultdict(
    lambda: deque(maxlen=CONVERSATION_MEMORY_TURNS * 2)
)


# ─── Request/Response models ───────────────────────────────────────────
class ChatRequest(BaseModel):
    conversation_id: str = Field(..., description="Client-generated unique ID")
    message: str = Field(..., min_length=1, description="User's question")
    mode: str = Field("clean", description="'clean' or 'dev'")
    temperature: float = Field(DEFAULT_TEMPERATURE, ge=0.0, le=2.0)
    similarity_threshold: float = Field(DEFAULT_SIMILARITY_THRESHOLD, ge=0.0, le=1.0)
    match_count: int = Field(DEFAULT_MATCH_COUNT, ge=1, le=20)
    ego: float = Field(0.5, ge=0.0, le=1.0, description="0=self-deprecating, 0.5=neutral, 1=emperor")


# ─── Core RAG logic ────────────────────────────────────────────────────

async def rewrite_query_for_retrieval(question: str, history: list) -> str:
    if not history:
        return question

    recent = history[-6:]
    history_text = "\n".join(
        f"{m['role'].capitalize()}: {m['content'][:200]}" for m in recent
    )

    rewrite_prompt = f"""You are rewriting a follow-up question into a standalone search query.

If the follow-up is vague ("tell me more", "why", "what about that", "expand"), YOU MUST rewrite it using context from the conversation so it becomes specific and searchable.

If the follow-up is already specific and standalone, return it unchanged.

CONVERSATION:
{history_text}

FOLLOW-UP: {question}

STANDALONE QUERY (output only the rewritten question, no explanation):"""

    try:
        response = genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=rewrite_prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=200,
            ),
        )
        rewritten = response.text.strip()
        return rewritten if rewritten else question
    except Exception:
        return question


def embed_query(text: str) -> list[float]:
    result = genai_client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=[text],
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    return result.embeddings[0].values


def retrieve_chunks(query_embedding: list, threshold: float, count: int):
    result = supabase.rpc(
        "match_knowledge",
        {
            "query_embedding": query_embedding,
            "match_threshold": threshold,
            "match_count": count,
        },
    ).execute()
    return result.data or []


def build_messages(
    history: list, question: str, chunks: list, mode: str, ego: float = 0.5
) -> list:
    base_system = DEV_SYSTEM_PROMPT if mode == "dev" else CLEAN_SYSTEM_PROMPT
    ego_block = ego_instruction(ego)
    system = base_system + ego_block

    if chunks:
        context_block = "\n\n".join(
            f"— EXCERPT {i+1} (from: {c['source_doc']}, similarity: {c['similarity']:.2f}) —\n{c['content']}"
            for i, c in enumerate(chunks)
        )
    else:
        context_block = "(No relevant context found in indexed writing.)"

    preamble = f"{system}\n\nRETRIEVED CONTEXT:\n{context_block}"

    messages = []

    for m in history:
        role = "user" if m["role"] == "user" else "model"
        messages.append({"role": role, "parts": [{"text": m["content"]}]})

    messages.append({
        "role": "user",
        "parts": [{"text": f"{preamble}\n\nQUESTION: {question}"}],
    })

    return messages


# ─── Endpoints ─────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "model": GENERATION_MODEL}


@app.get("/config")
async def get_config():
    """Returns public configuration for the frontend."""
    return {
        "name": USER_NAME,
        "model": GENERATION_MODEL,
    }


@app.post("/chat")
async def chat(req: ChatRequest):
    history = list(conversations[req.conversation_id])

    async def event_generator():
        try:
            search_query = await rewrite_query_for_retrieval(req.message, history)
            embedding = embed_query(search_query)
            chunks = retrieve_chunks(embedding, req.similarity_threshold, req.match_count)

            sources_payload = [
                {
                    "source_doc": c["source_doc"],
                    "similarity": round(c["similarity"], 3),
                    "content": c["content"],
                }
                for c in chunks
            ]
            yield f"data: {json.dumps({'type': 'sources', 'sources': sources_payload, 'rewritten_query': search_query})}\n\n"

            messages = build_messages(history, req.message, chunks, req.mode, req.ego)

            stream = genai_client.models.generate_content_stream(
                model=GENERATION_MODEL,
                contents=messages,
                config=types.GenerateContentConfig(
                    temperature=req.temperature,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                ),
            )

            full_response = []
            for chunk in stream:
                if chunk.text:
                    full_response.append(chunk.text)
                    yield f"data: {json.dumps({'type': 'token', 'text': chunk.text})}\n\n"
                    await asyncio.sleep(0)

            assistant_message = "".join(full_response)
            conversations[req.conversation_id].append({"role": "user", "content": req.message})
            conversations[req.conversation_id].append({"role": "assistant", "content": assistant_message})

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/conversations/{conversation_id}/reset")
async def reset_conversation(conversation_id: str):
    if conversation_id in conversations:
        del conversations[conversation_id]
    return {"status": "reset", "conversation_id": conversation_id}


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    return {
        "conversation_id": conversation_id,
        "history": list(conversations.get(conversation_id, [])),
    }
