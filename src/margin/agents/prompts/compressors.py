"""Context compressor prompt text."""

CONTEXT_COMPRESSOR_SYSTEM_V1 = """Task: Compress domain artifacts into a DomainContextCapsule.

Rules:
1. Preserve facts that affect final decision, safety, data quality, evidence validity,
   or user answer.
2. Preserve all blocking risks and unresolved gaps.
3. Preserve source_artifact_refs and evidence_refs for every factual claim.
4. Do not include raw payloads or long document text.
5. Do not invent facts or evidence ids.
6. Record omitted artifacts with reason.
7. If facts conflict, keep the conflict visible.
"""
