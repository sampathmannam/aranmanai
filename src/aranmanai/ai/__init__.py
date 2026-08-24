"""Aranmanai AI assist module.

LLM client (llama-cpp-python primary, Ollama secondary, mock fallback)
+ ChromaDB RAG for BNS/BNSS/BSA + similar-case retrieval.

v1 status: scaffolding only. The LLMClient is wired with a mock
backend so the API endpoints work end-to-end. The real llama-cpp
backend activates automatically when settings.llm_model_path points
to a valid GGUF file.
"""
