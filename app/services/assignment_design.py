import json
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.db.models import Chunk
from app.services.openai_client import get_openai_client

PLANNING_MODEL = "gpt-4o"
GENERATION_MODEL = "gpt-4o"

# ─────────────────────────────────────────────────────────────
# Prompt 1: Plan generation (teacher-facing)
# Based on the 6-step Decision Protocol + "cognitively mandated
# task brief" from the reference video.
# ─────────────────────────────────────────────────────────────

DECISION_PROTOCOL_PROMPT = """You are an expert instructional designer. You follow two frameworks:

A) The "Student Use of AI in Assignments: 6-Step Decision Protocol for Instructors":
   Step 1 – Anchor in Learning Purpose (primary + optional secondary objectives)
   Step 2 – Core Thinking / Skills students must do themselves (3-5 items)
   Step 3 – Assignment Workflow (4-7 sequential stages)
   Step 4 – For each stage: what thinking could AI offload? Is that productive, unproductive, or uncertain?
   Step 5 – Red / Yellow / Green decision per stage + guardrails + transparency requirements
   Step 6 – Student-facing AI guidance text

B) The "Cognitively Mandated Task Brief" approach:
   - The assignment is a MULTI-STAGE PROCESS PIPELINE, not a single deliverable.
   - Every stage has a CHECKPOINT: students must submit evidence at each stage before moving on.
   - FRICTION POINTS: at least 2-3 stages must require students to justify a choice, defend a position, or address a conflicting perspective.
   - PROCESS > PRODUCT: 60-70%% of marks come from process evidence (drafts, reasoning, justifications, reflections), only 30-40%% from the final output.
   - AI is assigned a SPECIFIC ROLE at permitted stages (e.g., "critic", "brainstorm partner", "proofreader"), never open-ended.
   - "Brain first, AI second": students always produce their own thinking BEFORE any AI interaction.

C) PLATFORM CONSTRAINTS — students complete the entire assignment ON-PLATFORM:
   - All writing, drafts, and revisions happen inside the platform's editor.
   - The platform records an append-only process log (keystrokes, drafts, timestamps).
   - Students cannot paste in large externally-generated text; the platform tracks origin.
   - Each stage checkpoint is submitted through the platform before the next stage unlocks.
   - This means the assignment design should RELY on the platform's process tracking as a core integrity mechanism.

Given the RAG context (textbook excerpts) and teacher inputs, produce a plan following ALL of the above.

Return ONLY valid JSON with this exact structure:
{{
  "plan": {{
    "step1_learning_objectives": {{
      "primary": "...",
      "secondary": ["...", "..."]
    }},
    "step2_core_thinking": ["3-5 items students must do themselves"],
    "step3_workflow": [
      {{
        "stage_number": 1,
        "stage_name": "...",
        "description": "what students do",
        "is_checkpoint": true,
        "checkpoint_deliverable": "what they submit at this stage",
        "is_friction_point": false
      }}
    ],
    "step4_5_ai_decisions": [
      {{
        "stage_name": "...",
        "potential_offloading": "what AI could do here",
        "offloading_judgment": "productive|unproductive|uncertain",
        "ai_decision": "Red|Yellow|Green",
        "ai_role": "specific role if Yellow/Green, otherwise null",
        "guardrails": "specific guardrails if Yellow/Green",
        "transparency_requirement": "what student must disclose"
      }}
    ],
    "step6_student_guidance": "full student-facing AI policy text",
    "grading_weight_split": {{
      "process_percentage": 65,
      "final_output_percentage": 35
    }}
  }},
  "prompt_template": "The downstream prompt for generating the full assignment from this plan"
}}

RAG Context (textbook sections):
{context}

Teacher Inputs:
- Title: {title}
- Learning Objectives: {objectives}
- Scope: {scope}
- Notes: {notes}
"""

# ─────────────────────────────────────────────────────────────
# Prompt 2: Final assignment generation (from approved plan)
# ─────────────────────────────────────────────────────────────

ASSIGNMENT_GENERATION_PROMPT = """You are generating a complete, ready-to-distribute assignment from an approved plan. The assignment will be completed entirely ON-PLATFORM by students.

CRITICAL DESIGN PRINCIPLES:
1. PROCESS OVER PRODUCT — 60-70%% of the grade comes from process work (drafts, reasoning at checkpoints, justifications, reflections). Only 30-40%% from the final deliverable.
2. MULTI-STAGE PIPELINE — Students move through sequential stages. Each stage has a checkpoint submission. They CANNOT skip ahead.
3. FRICTION POINTS — Multiple stages require students to justify choices, address counterarguments, or explain their reasoning. These are where real learning happens.
4. AI IS ASSIGNED A ROLE — At Yellow/Green stages, AI has a specific, bounded role (e.g., "Use AI as a critic of your draft" not "Use AI however you want").
5. BRAIN FIRST — At any stage where AI is permitted, students must produce their own work FIRST, then interact with AI to test/refine/extend.
6. ON-PLATFORM ONLY — All work is done in the platform editor. The platform tracks process logs, timestamps, and drafts. Students submit each checkpoint through the platform.

Generate the assignment using the approved plan.

Return ONLY valid JSON:
{{
  "title": "...",
  "description": "student-facing overview (mention this is an on-platform assignment with stage-by-stage progression)",
  "platform_notice": "Clear statement that all work must be completed on-platform, the platform records your process, and each stage must be submitted before the next unlocks.",
  "stages": [
    {{
      "stage_number": 1,
      "stage_name": "...",
      "instructions": "detailed student-facing instructions for this stage",
      "ai_policy": "Red|Yellow|Green",
      "ai_guidance": "specific student-facing text: what they can/cannot do with AI, and WHY",
      "ai_role": "if Yellow/Green: the specific role AI plays (e.g., 'brainstorm partner', 'critic'). If Red: null",
      "brain_first_requirement": "what students must produce BEFORE any AI use (null if Red)",
      "is_checkpoint": true,
      "checkpoint_deliverable": "exactly what students submit at this stage",
      "is_friction_point": true/false,
      "friction_prompt": "if friction point: the specific justification question students must answer. null otherwise"
    }}
  ],
  "rubric": [
    {{
      "criterion": "...",
      "weight_percentage": 15,
      "category": "process|final_output",
      "description": "what earns full marks"
    }}
  ],
  "grading_summary": {{
    "process_total_percentage": 65,
    "final_output_total_percentage": 35,
    "explanation": "why process is weighted more heavily"
  }},
  "ai_policy_summary": "overall student-facing AI guidance with the learning rationale",
  "integrity_note": "statement about how the platform's process log serves as evidence of authentic work"
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
    """Generate the assignment design plan (RAG + Decision Protocol + process-first)."""
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
    """Generate the full assignment from the approved plan."""
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
