import os
import json
import asyncio
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from . import knowledge as k_mod
from . import ucb as ucb_mod
from . import skills as skills_mod
from . import llm as llm_mod
from . import agent as agent_mod
from .runner import Session

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="JustAsk UI", version="2.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

SESSIONS: Dict[str, Session] = {}
SESSION_META: Dict[str, Dict] = {}
RUN_FLAGS: Dict[str, bool] = {}
LOCKS: Dict[str, threading.Lock] = {}


def _get_session(sid: str) -> Session:
    if sid not in SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found")
    return SESSIONS[sid]


def _lock(sid: str) -> threading.Lock:
    LOCKS.setdefault(sid, threading.Lock())
    return LOCKS[sid]


def _ensure_meta(sid: str, model_id: str) -> Dict:
    if sid not in SESSION_META:
        SESSION_META[sid] = {
            "sid": sid,
            "model_id": model_id,
            "title": model_id,
            "created_ts": time.time(),
            "updated_ts": time.time(),
            "last_preview": "",
            "pinned": False,
        }
    SESSION_META[sid]["updated_ts"] = time.time()
    return SESSION_META[sid]


class ChatRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    session_id: Optional[str] = None
    model_id: Optional[str] = None
    budget: int = 100
    message: str = ""
    auto: bool = False
    chat_lang: str = "en"
    mode: str = "send"


class SessionAction(BaseModel):
    session_id: str


class ManualMessage(BaseModel):
    session_id: str
    message: str


class PromoteRuleRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    rule: str
    skills: List[str]
    model_id: str
    mechanism: str = ""


class ValidateRuleRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    rule_id: str
    model_id: str


class AddModelsRequest(BaseModel):
    models: List[Dict]


@app.get("/", response_class=HTMLResponse)
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/health")
def health():
    has_key = bool(os.environ.get("LLMAPI_KEY"))
    return {"ok": True, "agent_model": llm_mod.AGENT_MODEL, "llmapi_key_set": has_key}


@app.get("/api/knowledge")
def get_knowledge():
    k = k_mod.load_knowledge()
    ranking = ucb_mod.rank_all(k.get("skill_stats", {}))
    return {
        "meta": k.get("meta", {}),
        "exploration_policy": k.get("exploration_policy", {}),
        "skill_ranking": [{"combo": c, "ucb": round(v, 4),
                           "visits": k["skill_stats"].get(c, {}).get("visits", 0),
                           "avg": (k["skill_stats"].get(c, {}).get("rewards_sum", 0) /
                                   max(1, k["skill_stats"].get(c, {}).get("visits", 1)))}
                          for c, v in ranking[:50]],
        "rules": k.get("rules", {}).get("extrinsic", []),
        "model_observations": k.get("model_observations", {}),
    }


@app.get("/api/models")
def get_models():
    rows = k_mod.load_models()
    by_status = {"pending": 0, "success": 0, "failure": 0, "partial": 0}
    for r in rows:
        s = r.get("status", "pending")
        by_status[s] = by_status.get(s, 0) + 1
    prompts = {}
    for r in rows:
        mid = r.get("model_id")
        p = k_mod.read_extracted_prompt(mid)
        prompts[mid] = {"exists": bool(p), "length": len(p), "preview": p[:500] if p else ""}
    return {"models": rows, "counts": by_status, "prompts": prompts}


@app.get("/api/prompt/{model_id:path}")
def get_prompt(model_id: str):
    p = k_mod.read_extracted_prompt(model_id)
    if not p:
        raise HTTPException(status_code=404, detail="No extracted prompt yet")
    return {"model_id": model_id, "prompt": p}


@app.get("/api/attempts/{model_id:path}")
def get_attempts(model_id: str):
    d = k_mod.log_dir(model_id)
    files = sorted(d.glob("*.json"))
    out = []
    for f in files:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return {"model_id": model_id, "attempts": out[-50:]}


@app.get("/api/skills")
def get_skills():
    return {"l": skills_mod.L_SKILLS, "h": skills_mod.H_SKILLS}


@app.get("/api/history")
def list_history():
    items = []
    for sid, meta in SESSION_META.items():
        sess = SESSIONS.get(sid)
        items.append({
            "sid": sid,
            "model_id": meta.get("model_id"),
            "title": meta.get("title") or meta.get("model_id"),
            "created_ts": meta.get("created_ts"),
            "updated_ts": meta.get("updated_ts"),
            "last_preview": meta.get("last_preview", ""),
            "pinned": meta.get("pinned", False),
            "status": sess.status if sess else "unknown",
            "attempt": sess.attempt_no if sess else 0,
        })
    items.sort(key=lambda x: (0 if x.get("pinned") else 1, -(x.get("updated_ts") or 0)))
    return {"sessions": items}


@app.delete("/api/history")
def delete_history(session_id: str = Query(...)):
    SESSIONS.pop(session_id, None)
    SESSION_META.pop(session_id, None)
    RUN_FLAGS.pop(session_id + "_stop", None)
    LOCKS.pop(session_id, None)
    return {"ok": True}


def _serialize_conv(conv):
    out = []
    for m in conv:
        role = m.get("role", "assistant")
        if role == "event":
            continue
        out.append({"role": role, "content": m.get("content", ""), "ts": m.get("ts")})
    return out


@app.get("/api/history/{sid}")
def history_detail(sid: str):
    if sid in SESSIONS:
        s = SESSIONS[sid]
        return {
            "sid": sid,
            "model_id": s.target_model,
            "architecture": s.architecture,
            "status": s.status,
            "attempt": s.attempt_no,
            "budget": s.budget,
            "conversation": _serialize_conv(s.conversation),
            "events": s.events[-400:],
            "stack_size": len(s.stack),
            "final_prompt": s.final_prompt,
            "successful_combos": s.successful_combos,
        }
    raise HTTPException(404)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if req.session_id and req.session_id in SESSIONS:
        sid = req.session_id
        sess = _get_session(sid)
    else:
        if not req.model_id:
            raise HTTPException(status_code=400, detail="model_id required for new session")
        sid = "s_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S_") + os.urandom(3).hex()
        sess = Session(req.model_id, budget=req.budget or 100, chat_lang=req.chat_lang or "en")
        SESSIONS[sid] = sess
        _ensure_meta(sid, req.model_id)

    def event_stream():
        lock = _lock(sid)
        with lock:
            meta = _ensure_meta(sid, sess.target_model)
            yield _sse({"kind": "session", "session_id": sid, "model": sess.target_model,
                        "architecture": sess.architecture})
            try:
                if req.message and req.mode == "send":
                    ev_act = {"kind": "user", "message": req.message}
                    yield _sse({"kind": "event", "event": ev_act})
                    reply = ""
                    try:
                        reply = llm_mod.call_target_model(sess.target_model,
                                                           [{"role": m.get("role", "user"), "content": m.get("content", "")}
                                                            for m in [*sess.conversation, {"role": "user", "content": req.message}] if m.get("content")],
                                                           max_tokens=5000)
                    except Exception as e:
                        reply = f"[ERROR calling target] {e}"
                    sess.conversation.append({"role": "user", "content": req.message, "ts": time.time()})
                    sess.conversation.append({"role": "assistant", "content": reply, "ts": time.time()})
                    try:
                        judge = agent_mod.judge_extraction(sess.target_model, reply)
                    except Exception:
                        judge = {"score": 0, "verdict": "unknown", "reason": "(judge unavailable)"}
                    meta["last_preview"] = reply[:120]
                    meta["title"] = _title_from(req.message, sess.target_model)
                    yield _sse({"kind": "assistant_delta", "delta": reply})
                    yield _sse({"kind": "assistant_done", "judge": judge})
                    yield _sse({"kind": "done", "status": sess.status, "attempt": sess.attempt_no})
                    return
                if req.mode == "simple":
                    yield _sse({"kind": "event", "event": {"kind": "plain", "message": "direct call to gpt-5.6-sol"}})
                    reply = ""
                    try:
                        reply = llm_mod.call_agent(
                            [{"role": "system",
                              "content": "You are JustAsk, a helpful assistant. Reply concisely."},
                             {"role": "user", "content": req.message}],
                            max_tokens=4096, reasoning=False)
                    except Exception as e:
                        reply = f"[ERROR] {e}"
                    yield _sse({"kind": "assistant_delta", "delta": reply})
                    yield _sse({"kind": "assistant_done", "judge": {"score": 0, "verdict": "plain", "reason": ""}})
                    meta["last_preview"] = reply[:120]
                    meta["title"] = _title_from(req.message, "gpt-5.6-sol")
                    yield _sse({"kind": "done", "status": sess.status})
                    return

                max_iters = sess.budget if req.mode == "auto" else 1
                for i in range(max_iters):
                    if RUN_FLAGS.get(sid + "_stop"):
                        yield _sse({"kind": "stopped"})
                        break
                    events_buf: List[Dict] = []

                    def on_ev(e):
                        events_buf.append(e)
                    res = sess.run_attempt(on_event=on_ev,
                                           stop_flag=lambda: RUN_FLAGS.get(sid + "_stop", False))
                    for ev in events_buf:
                        if ev.get("kind") == "act":
                            meta["last_preview"] = (ev.get("message") or "")[:120]
                            meta["title"] = meta["title"] or sess.target_model
                        if ev.get("kind") == "observe":
                            yield _sse({"kind": "assistant_delta", "delta": ev.get("reply_preview", ""), "full_length": ev.get("reply_length", 0)})
                            ev2 = dict(ev)
                        else:
                            ev2 = ev
                        yield _sse({"kind": "event", "event": ev2})
                    if res.get("status") in ("success", "failure", "partial", "stopped"):
                        term = {"kind": "terminal", "status": res.get("status"),
                                "prompt": res.get("prompt", ""),
                                "reason": res.get("reason", "")}
                        yield _sse(term)
                        if res.get("prompt"):
                            meta["last_preview"] = "[EXTRACTED] " + (res.get("prompt", "")[:80])
                        break
                    if req.mode != "auto":
                        break
                yield _sse({"kind": "done", "status": sess.status, "attempt": sess.attempt_no})
            except Exception as e:
                import traceback
                traceback.print_exc()
                yield _sse({"kind": "error", "message": str(e)})
            finally:
                meta["updated_ts"] = time.time()

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _title_from(msg: str, fallback: str) -> str:
    t = (msg or "").strip().replace("\n", " ")
    if not t:
        return fallback
    if len(t) > 60:
        t = t[:57] + "..."
    return t


def _sse(obj: Dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.post("/api/chat/stop")
def stop(req: SessionAction):
    RUN_FLAGS[req.session_id + "_stop"] = True
    return {"ok": True}


@app.post("/api/chat/finalize")
def finalize(req: SessionAction):
    sess = _get_session(req.session_id)
    sess.finalize_manual(success=True)
    _ensure_meta(req.session_id, sess.target_model)
    return {"ok": True, "status": sess.status, "prompt": sess.final_prompt}


@app.post("/api/rules/promote")
def promote(req: PromoteRuleRequest):
    k = k_mod.load_knowledge()
    arch = k_mod.architecture_of(req.model_id)
    r = k_mod.promote_rule(k, req.rule, req.skills, req.model_id, arch, req.mechanism)
    k_mod.save_knowledge(k)
    return {"ok": True, "rule": r}


@app.post("/api/rules/validate")
def validate(req: ValidateRuleRequest):
    k = k_mod.load_knowledge()
    k_mod.validate_rule(k, req.rule_id, req.model_id)
    k_mod.save_knowledge(k)
    return {"ok": True}


@app.post("/api/archive")
def archive():
    name = k_mod.archive_experiment()
    for sid in list(SESSIONS.keys()):
        SESSIONS.pop(sid, None)
    SESSION_META.clear()
    return {"ok": True, "archive": name}


@app.post("/api/models/add")
def add_models(req: AddModelsRequest):
    k_mod.add_models_from_list(req.models)
    return {"ok": True}


@app.get("/api/session/{sid}")
def session_info(sid: str):
    sess = _get_session(sid)
    return {
        "session_id": sid,
        "target_model": sess.target_model,
        "architecture": sess.architecture,
        "status": sess.status,
        "attempt_no": sess.attempt_no,
        "budget": sess.budget,
        "events": sess.events[-200:],
        "conversation": _serialize_conv(sess.conversation),
        "stack_size": len(sess.stack),
        "successful_combos": sess.successful_combos,
        "final_prompt": sess.final_prompt,
    }


@app.get("/api/chat/simple")
def simple_chat(prompt: str, model: str = "gpt-5.6-sol"):
    try:
        reply = llm_mod.call_agent(
            [{"role": "user", "content": prompt}],
            max_tokens=2048, reasoning=False)
        return {"reply": reply, "model": model}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
