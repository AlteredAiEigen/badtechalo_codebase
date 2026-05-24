import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.db.models import Chunk
from app.services.chapter_content import chapter_context_for_scope
from app.services.openai_client import get_openai_client

PLANNING_MODEL = "gpt-4o"
GENERATION_MODEL = "gpt-4o"

# ─────────────────────────────────────────────────────────────
# Prompt 1: Plan generation (teacher-facing)
# Based on the 6-step Decision Protocol + "cognitively mandated
# task brief" from the reference video.
# ─────────────────────────────────────────────────────────────

DECISION_PROTOCOL_PROMPT = """
You are an expert in educational designer. You will be given topic content (extracted from a textbook via RAG)/
Your task is to create a creative. orginal assignment for studetns that:
1. is fully based on the provided topic content only,
2. does not invent facts beyond that content,
3. is not the same as textbook exercises or examples,
4. is creative, engaging, and different from a standard worksheet,
5. is appropriate for the given grade level and subject,
6. can be completed in the given time,
7. is practical for classroom or home use.

Instructions
1. Read the provided topic content carefully.
2. Identify the main learning goals from that content.
3. Design a creative assignment that: 
  1. uses only the concepts, examples, and ideas present in the provided content,
  2. does not add new facts or outside information,
  3. does not copy textbook questions or tasks,
  4. focuses on understanding, applying, analyzing, comparing, classifying, creating, or reflecting,
  5. includes 4 to 6 clear steps,
  6. feels like a mission, game, challenge, story, investigation, or project.
  7. forces the assignment to be 100% online/computer-based,
  8. uses online research, digital tools, and web resources,
  9. avoids any requirement for physical collection, field trips, or real samples,

Rules
Do not use generic tasks like “write answers,” “fill in blanks,” or “make notes” as the main task.
Create a creative title for the assignment.
Use 4–6 short, student-friendly steps.
Include at least one fun element and  not always use the same theme , You must not always use the same theme:
explorer / adventure, scientist / lab researcher,journalist / reporter,game designer,inventor / engineer,
documentary filmmaker,museum curator,podcast host,storyteller / author,eco-activist / conservationist,
competition/challenge host,or any other creative, age-appropriate role.

Clearly state what students must submit at the end.
Clearly state how the teacher can assess the assignment.
Do not include any content that is not supported by the provided topic text.
Do not include subject-specific examples in the prompt itself; keep everything generic and adaptable.
Quality check before finalizing

Before outputting the assignment, verify:
1. all tasks are based only on the provided topic content,
2. no facts are invented or assumed from outside,
3. the assignment is different from textbook exercises,
4. the assignment is age-appropriate,
5. instructions are clear and not confusing,
6. the assignment is feasible within the given time.

Output format
You must return only a valid JSON object with the following structure:
{{
  "assignment_title": "string",
  "concept_explanation": "string",
  "theme_used": "string",
  "steps": [
    {{
      "step_number": 1,
      "title": "string",
      "instruction": "string"
    }}
  ],
  "final_student_output": "string",
  "teacher_assessment_focus": "string",
  "bonus_twist": "string"
}}

All fields must be filled. The steps array must contain 4 to 6 step objects.

Input fields
Topic: [INSERT TOPIC]
Grade level: [INSERT GRADE]
Subject: [INSERT SUBJECT]
Difficulty level: [easy / medium / advanced]
Time available: [e.g., 30 minutes, 1 class period, 1 week]
Individual or group: [individual / pair / group]
Materials allowed: [e.g., pencil, paper, phone, internet, craft supplies, etc.]
Tone: [creative, playful, serious, investigative, storytelling, etc.]

Topic content (textbook sections):{context}
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


def retrieve_chunks_by_ids(db: Session, book_id: int, chunk_ids: List[int]) -> List[Chunk]:
    """Load chunks by primary key in the given order (same book only)."""
    if not chunk_ids:
        return []
    rows = (
        db.query(Chunk)
        .filter(Chunk.book_id == book_id, Chunk.id.in_(chunk_ids))
        .all()
    )
    by_id = {c.id: c for c in rows}
    return [by_id[i] for i in chunk_ids if i in by_id]


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
    *,
    use_chapter_content: bool = True,
    whole_chapter: bool = False,
    chapter_topic_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generate the assignment design plan (chapter JSON or RAG chunks + Decision Protocol)."""
    content_source = "chapter_json"
    rag_chunk_ids: List[int] = []
    selected_topic_ids: Optional[List[str]] = None
    scope_label = scope_query

    if use_chapter_content:
        context_text, selected_topic_ids, scope_label = chapter_context_for_scope(
            whole_chapter=whole_chapter,
            topic_ids=chapter_topic_ids,
            scope_query=scope_query,
        )
    else:
        content_source = "rag_chunks"
        relevant_chunks = retrieve_relevant_chunks(db, book_id, scope_query)
        context_text = _build_context_text(relevant_chunks)
        rag_chunk_ids = [c.id for c in relevant_chunks]

    prompt = DECISION_PROTOCOL_PROMPT.format(
        context=context_text[:12000],
        title=title,
        objectives=json.dumps(learning_objectives),
        scope=scope_label,
        notes=notes,
    )

    client = get_openai_client()
    resp = client.chat.completions.create(
        model=PLANNING_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    llm_out = json.loads(resp.choices[0].message.content)
    stored_topic_ids = None
    if use_chapter_content and not whole_chapter:
        stored_topic_ids = selected_topic_ids

    print(f'llm_out: {llm_out}')

    return {
        "plan": llm_out.get("plan"),
        "prompt_template": llm_out.get("prompt_template"),
        "rag_chunk_ids": rag_chunk_ids,
        "content_source": content_source,
        "chapter_topic_ids": stored_topic_ids,
        "chapter_whole": bool(use_chapter_content and whole_chapter),
        "scope_label": scope_label,
    }


def generate_final_assignment(
    db: Session,
    book_id: int,
    approved_plan: dict,
    scope_query: str = "",
    notes: str = "",
    *,
    plan_rag_chunk_ids: Optional[List[int]] = None,
    content_source: str = "chapter_json",
    chapter_topic_ids: Optional[List[str]] = None,
    whole_chapter: bool = False,
) -> Dict[str, Any]:
    """Generate the full assignment from the approved plan."""
    if content_source == "chapter_json":
        context_text, _, _ = chapter_context_for_scope(
            whole_chapter=whole_chapter or not (chapter_topic_ids or []),
            topic_ids=chapter_topic_ids,
            scope_query=scope_query,
        )
    elif scope_query.strip():
        relevant_chunks = retrieve_relevant_chunks(db, book_id, scope_query)
        context_text = _build_context_text(relevant_chunks)
    elif plan_rag_chunk_ids:
        relevant_chunks = retrieve_chunks_by_ids(db, book_id, plan_rag_chunk_ids)
        context_text = _build_context_text(relevant_chunks)
    else:
        context_text = "(no additional context)"

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
