"""
backend.tech_assist — Sprint 7 Tech Assist module (MaintainX-AI lineage).

Sub-modules:
  troubleshoot.py  Sprint 7.1a — Real-time repair assistance QA
  models.py        Pydantic DTOs
  routes.py        FastAPI router /api/tech-assist/*

Future (deferred):
  document_ingest.py  PDF + image -> ChromaDB
  voice_normalizer.py Whisper + LLM -> professional report
  nameplate_ocr.py    easyocr -> structured asset metadata
  sop_generator.py    Manual chunk -> procedure YAML
"""

from .troubleshoot import TroubleshootAgent, get_troubleshoot_agent  # noqa: F401
