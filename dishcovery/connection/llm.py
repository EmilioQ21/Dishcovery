"""Minimal client for any OpenAI-compatible /chat/completions endpoint.

Examples (.env):
  Groq (free tier):   LLM_BASE_URL=https://api.groq.com/openai/v1   LLM_MODEL=openai/gpt-oss-20b
  Gemini:             LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai   LLM_MODEL=gemini-2.0-flash
  OpenAI:             LLM_BASE_URL=https://api.openai.com/v1        LLM_MODEL=gpt-4o-mini
  Ollama (local):     LLM_BASE_URL=http://localhost:11434/v1        LLM_MODEL=llama3.2   (LLM_API_KEY=ollama)
"""
import requests

from dishcovery import config


def llm_configured():
    return bool(config.LLM_API_KEY)


def chat_completion(system_prompt, user_prompt, temperature=0.2):
    if not llm_configured():
        raise RuntimeError("LLM_API_KEY is not set (see .env.example)")
    resp = requests.post(
        config.LLM_BASE_URL.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + config.LLM_API_KEY, "Content-Type": "application/json"},
        json={
            "model": config.LLM_MODEL,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
        },
        timeout=config.LLM_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError("LLM request failed (%s, model %s): %s" % (resp.status_code, config.LLM_MODEL, resp.text[:300]))
    return resp.json()["choices"][0]["message"]["content"].strip()
