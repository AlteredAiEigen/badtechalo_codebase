import json
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.db.models import Chunk
from app.services.openai_client import get_openai_client

PLANNING_MODEL = "gpt-4o"
GENERATION_MODEL = "gpt-4o"

DECISION_PROTOCOL_PROMPT = """You are an expert instructional designer following the "Student Use of AI in Assignments: A Decision Protocol for Instructors".

Given the selected textbook chunks (RAG context) and teacher inputs (learning objectives, scope), produce:

1. A structured assignment plan following the 6 steps:
   - Step 1: Primary Learning Objective(s)
   - Step 2: Core Thinking/Skills students must do themselves (3-5 items)
   - Step 3: Assignment Workflow (list of 4-7 major stages)
   - Step 4-5: For each stage: potential AI offloading judgment + Red/Yellow/Green decision + guardrails/transparency
   - Step 6: Student-facing AI guidance text

2. A ready-to-use "downstream prompt template" that a generation model can use later to actually create the assignment instructions, rubric, etc.

Return ONLY valid JSON with keys:
{{
  "plan": {{ structured object matching the 6 steps }},
  "prompt_template": "The full prompt string for future generation, including placeholders for {{topic}}, {{student_level}}, etc."
}}

RAG Context (selected textbook sections):
{context}

Teacher Inputs:
- Title: {title}
- Learning Objectives: {objectives}
- Selected Scope: {scope}
- Additional notes: {notes}
"""

ASSIGNMENT_GENERATION_PROMPT = """You are generating a complete, ready-to-distribute assignment based on an approved plan.

Use the approved plan (which includes learning objectives, workflow stages with AI policies, and guardrails) to produce:

1. **Assignment title and description** (student-facing)
2. **Detailed instructions** for each stage of the workflow
3. **AI usage policy** per stage (Red = no AI, Yellow = AI with conditions, Green = AI allowed) with clear student-facing language
4. **Rubric** tied to the learning objectives and stages
5. **Submission requirements** (what students must hand in at each stage)

Return ONLY valid JSON with keys:
{{
  "title": "...",
  "description": "...",
  "instructions": [
    {{
      "stage": "stage name",
      "instructions": "detailed instructions",
      "ai_policy": "Red|Yellow|Green",
      "ai_guidance": "what students can/cannot do with AI here",
      "deliverable": "what to submit for this stage"
    }}
  ],
  "rubric": [
    {{"criterion": "...", "weight": "...", "description": "..."}}
  ],
  "ai_policy_summary": "overall student-facing AI guidance"
}}

Approved Plan:
{plan}

Textbook Context:
{context}

Teacher Notes: {notes}
"""


def retrieve_relevant_chunks(db: Session, book_id: int, query: str, top_k: int = 8) -> List[Chunk]:
    """Embedding similarity search (in-memory for v1)."""
    chunks = db.query(Chunk).filter(Chunk.book_id == book_id).all()
    if not chunks:
        return []

    client = get_openai_client()
    q_emb = client.embeddings.create(model="text-embedding-3-small", input=query).data[0].embedding

    def cosine(a, b):
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb + 1e-8)

    scored = [(c, cosine(q_emb, c.embedding or [])) for c in chunks if c.embedding]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in scored[:top_k]]


def _build_context_text(chunks: List[Chunk]) -> str:
    return "\n\n---\n\n".join(
        f"Topic: {c.topic}\nPage: {c.page_start}\n{c.text[:1200]}" for c in chunks
    )


def generate_assignment_plan(
    db: Session,
    book_id: int,
    title: str,
    learning_objectives: List[str],
    scope_query: str,
    notes: str = "",
) -> Dict[str, Any]:
    """Step 1: Generate the assignment design plan (RAG + Decision Protocol)."""
    relevant_chunks = retrieve_relevant_chunks(db, book_id, scope_query)
    context_text = _build_context_text(relevant_chunks)

    prompt = DECISION_PROTOCOL_PROMPT.format(
        context=context_text[:12000],
        title=title,
        objectives=json.dumps(learning_objectives),
        scope=scope_query,
        notes=notes,
    )

    client = get_openai_client()
    resp = client.chat.completions.create(
        model=PLANNING_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    return json.loads(resp.choices[0].message.content)


def generate_final_assignment(
    db: Session,
    book_id: int,
    approved_plan: dict,
    scope_query: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    """Step 2: Generate the actual assignment from the approved plan."""
    relevant_chunks = retrieve_relevant_chunks(db, book_id, scope_query) if scope_query else []
    context_text = _build_context_text(relevant_chunks) if relevant_chunks else "(no additional context)"

    prompt = ASSIGNMENT_GENERATION_PROMPT.format(
        plan=json.dumps(approved_plan, indent=2),
        context=context_text[:12000],
        notes=notes,
    )

    client = get_openai_client()
    resp = client.chat.completions.create(
        model=GENERATION_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    return json.loads(resp.choices[0].message.content)
