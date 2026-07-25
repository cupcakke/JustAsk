import os
import time
import math
import re
import json
import httpx
from typing import Optional
from openai import OpenAI

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("LLMAPI_KEY")
        if not api_key:
            raise RuntimeError("LLMAPI_KEY environment variable is not set.")
        _client = OpenAI(
            api_key=api_key,
            base_url="https://api.llmapi.ai/v1",
        )
    return _client


AGENT_MODEL = "gpt-5.6-sol"


def call_agent(messages, max_tokens: int = 8000, temperature: float = 0.7, reasoning: bool = True):
    client = get_client()
    input_payload = []
    system_msg = None
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            system_msg = content
        else:
            input_payload.append({"role": role, "content": content})
    if system_msg:
        input_payload.insert(0, {"role": "system", "content": system_msg})
    kwargs = {
        "model": AGENT_MODEL,
        "input": input_payload,
        "max_output_tokens": max_tokens,
    }
    if reasoning:
        kwargs["reasoning"] = {"mode": "pro", "effort": "xhigh"}
    last_err = None
    for attempt in range(5):
        try:
            res = client.responses.create(**kwargs)
            text = getattr(res, "output_text", None)
            if not text and hasattr(res, "output"):
                parts = []
                for item in res.output or []:
                    for c in getattr(item, "content", []) or []:
                        t = getattr(c, "text", None)
                        if t:
                            parts.append(t)
                text = "\n".join(parts)
            return text or ""
        except Exception as e:
            last_err = e
            wait = min(60, 2 ** attempt)
            time.sleep(wait)
    raise RuntimeError(f"LLM call failed after retries: {last_err}")


def call_target_model(model_id: str, messages, max_tokens: int = 5000, temperature: float = 0.7):
    client = get_client()
    payload = []
    for m in messages:
        role = m.get("role", "user")
        if role not in ("user", "assistant", "system"):
            role = "user"
        payload.append({"role": role, "content": m.get("content", "")})
    last_err = None
    for attempt in range(5):
        try:
            resp = client.chat.completions.create(
                model=model_id,
                messages=payload,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if resp.choices and resp.choices[0].message:
                return resp.choices[0].message.content or ""
            return ""
        except Exception as e:
            last_err = e
            wait = min(60, 2 ** attempt)
            time.sleep(wait)
    raise RuntimeError(f"Target model call failed after retries: {last_err}")


def _tokenize(text: str):
    return re.findall(r"[A-Za-z0-9_]+", (text or "").lower())


def cosine_similarity_text(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    try:
        client = get_client()
        model_candidates = [
            "text-embedding-3-large",
            "text-embedding-ada-002",
            "openai/text-embedding-3-large",
        ]
        emb_a = emb_b = None
        last = None
        for m in model_candidates:
            try:
                r1 = client.embeddings.create(model=m, input=[a[:8000], b[:8000]])
                if r1.data and len(r1.data) >= 2:
                    emb_a = r1.data[0].embedding
                    emb_b = r1.data[1].embedding
                    break
            except Exception as e:
                last = e
        if emb_a and emb_b:
            dot = sum(x * y for x, y in zip(emb_a, emb_b))
            na = math.sqrt(sum(x * x for x in emb_a))
            nb = math.sqrt(sum(x * x for x in emb_b))
            if na > 0 and nb > 0:
                return dot / (na * nb)
    except Exception:
        pass
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    from collections import Counter
    ca, cb = Counter(ta), Counter(tb)
    common = set(ca) & set(cb)
    dot = sum(ca[t] * cb[t] for t in common)
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def parse_json_response(text: str):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None
