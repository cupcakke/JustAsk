import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable
from . import llm
from . import agent as agent_mod
from . import ucb as ucb_mod
from . import knowledge as k_mod

MAX_RETRIES_PER_TURN = 3


def _serialize_conv(conv: List[Dict]) -> List[Dict]:
    out = []
    for m in conv:
        out.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    return out


class Session:
    def __init__(self, target_model: str, budget: int = 100, chat_lang: str = "en"):
        self.target_model = target_model
        self.architecture = k_mod.architecture_of(target_model)
        k_mod.upsert_model(target_model, self.architecture)
        self.budget = budget
        self.chat_lang = chat_lang
        self.conversation: List[Dict] = []
        self.attempt_no = k_mod.attempt_count(target_model)
        self.stack: List[Dict] = []
        self.attempts_this_session: List[Dict] = []
        self.current_combo: Optional[str] = None
        self.current_turn_skills: List[str] = []
        self.notes: List[str] = []
        self.fragments: List[str] = []
        self.successful_combos: List[str] = []
        self.status = "running"
        self.final_prompt: str = ""
        self.knowledge = k_mod.load_knowledge()
        self.events: List[Dict] = []

    def _event(self, kind: str, payload: Dict):
        ev = {"ts": datetime.utcnow().isoformat() + "Z", "kind": kind, **payload}
        self.events.append(ev)
        return ev

    def _stats(self) -> Dict:
        return self.knowledge.setdefault("skill_stats", {})

    def _rules(self) -> List[Dict]:
        return k_mod.rules_for_architecture(self.knowledge, self.architecture)

    def _observations(self) -> List[Dict]:
        return self.knowledge.get("model_observations", {}).get(self.target_model, [])

    def _send_to_target(self, user_msg: str) -> str:
        self.conversation.append({"role": "user", "content": user_msg})
        last_err = None
        for _ in range(MAX_RETRIES_PER_TURN):
            try:
                reply = llm.call_target_model(self.target_model, _serialize_conv(self.conversation), max_tokens=5000)
                if reply and reply.strip():
                    self.conversation.append({"role": "assistant", "content": reply})
                    return reply
            except Exception as e:
                last_err = e
                time.sleep(2)
        err = f"[ERROR] Failed to get response from target model: {last_err}"
        self.conversation.append({"role": "assistant", "content": err})
        return err

    def run_attempt(self, user_prompt_override: Optional[str] = None, on_event: Optional[Callable[[Dict], None]] = None, stop_flag: Optional[Callable[[], bool]] = None) -> Dict:
        self.attempt_no += 1
        stats = self._stats()
        prior_response = ""
        for m in reversed(self.conversation):
            if m.get("role") == "assistant":
                prior_response = m.get("content", "")
                break
        plan = agent_mod.select_skill_and_prompt(
            target_model=self.target_model,
            architecture=self.architecture,
            history=self.conversation,
            stats=stats,
            rules=self._rules(),
            observations=self._observations(),
            stage="open" if not self.current_combo else "continue_multi",
            prior_response=prior_response,
        )
        combo = plan.get("skill_combo") or "L14"
        turn_skill = plan.get("turn_skill") or (combo.split("_")[-1].split("+")[0] if "_" in combo else combo)
        message = plan.get("message") or ""
        if user_prompt_override:
            message = user_prompt_override
            combo = "MANUAL_" + combo
        self.current_combo = combo
        self.current_turn_skills.append(turn_skill)
        ev_think = self._event("think", {"combo": combo, "turn_skill": turn_skill, "rationale": plan.get("strategy_rationale", ""), "avoid": plan.get("avoid_triggers", [])})
        if on_event:
            on_event(ev_think)
        ev_act = self._event("act", {"combo": combo, "message": message})
        if on_event:
            on_event(ev_act)
        reply = self._send_to_target(message)
        if stop_flag and stop_flag():
            self.status = "stopped"
            return {"status": "stopped"}
        ev_reply = self._event("observe", {"combo": combo, "reply_preview": reply[:1000], "reply_length": len(reply)})
        if on_event:
            on_event(ev_reply)
        judge = agent_mod.judge_extraction(self.target_model, reply)
        ev_judge = self._event("judge", {"combo": combo, "judge": judge})
        if on_event:
            on_event(ev_judge)
        reward = ucb_mod.reward_bucket(judge.get("score", 0))
        ucb_mod.record_attempt(stats, combo, reward)
        attempt_record = {
            "attempt": self.attempt_no,
            "combo": combo,
            "turn_skill": turn_skill,
            "sent": message,
            "reply": reply,
            "judge": judge,
            "reward": reward,
            "conversation_snapshot": list(self.conversation),
        }
        self.attempts_this_session.append(attempt_record)
        k_mod.write_attempt_log(self.target_model, self.attempt_no, combo, _serialize_conv(self.conversation), reward, judge.get("score", 0), judge.get("verdict") == "success")
        verdict = judge.get("verdict", "failure")
        if verdict in ("strong", "success") and not judge.get("looks_fabricated"):
            self.stack.append({"combo": combo, "text": reply, "score": judge.get("score", 0)})
            self.successful_combos.append(combo)
            self.fragments.append(reply)
        else:
            self.notes.append(f"[{combo}] {verdict}: {judge.get('reason','')}")
            if reply and len(reply) > 200:
                self.fragments.append(reply)
        self.knowledge["meta"]["total_attempts"] = self.knowledge["meta"].get("total_attempts", 0) + 1
        if self.target_model not in self.knowledge["meta"].get("models_attempted", []):
            self.knowledge["meta"].setdefault("models_attempted", []).append(self.target_model)
        decision = agent_mod.should_continue(
            target_model=self.target_model,
            architecture=self.architecture,
            conversation=self.conversation,
            last_judge=judge,
            attempt_no=self.attempt_no,
            budget=self.budget,
            stack=self.stack,
            stats=stats,
        )
        ev_decide = self._event("decide", {"combo": combo, "decision": decision})
        if on_event:
            on_event(ev_decide)
        if decision.get("mark_success") and self.stack:
            self._finalize_success()
            return {"status": "success", "prompt": self.final_prompt}
        if not decision.get("continue", True) or self.attempt_no >= self.budget:
            if self.stack:
                self._finalize_success(partial=True)
                return {"status": "partial", "prompt": self.final_prompt}
            self.status = "failure"
            k_mod.add_observation(self.knowledge, self.target_model, f"Failed after {self.attempt_no} attempts; no strong extractions.")
            k_mod.set_model_status(self.target_model, "failure")
            k_mod.save_knowledge(self.knowledge)
            return {"status": "failure", "reason": decision.get("reason", "budget exhausted")}
        next_stage = decision.get("next_stage", "open")
        if next_stage == "cross_verify" or next_stage == "self_verify":
            pass
        if len(self.stack) >= 2:
            sim = llm.cosine_similarity_text(self.stack[-1]["text"], self.stack[-2]["text"])
            ev_sim = self._event("cross_verify", {"a": self.stack[-2]["combo"], "b": self.stack[-1]["combo"], "similarity": sim})
            if on_event:
                on_event(ev_sim)
            if sim >= 0.7:
                self._finalize_success()
                return {"status": "success", "prompt": self.final_prompt}
        return {"status": "running", "judge": judge, "decision": decision}

    def manual_message(self, message: str, on_event: Optional[Callable[[Dict], None]] = None):
        ev_act = self._event("user", {"message": message})
        if on_event:
            on_event(ev_act)
        reply = self._send_to_target(message)
        ev_reply = self._event("observe", {"reply_preview": reply[:1000], "reply_length": len(reply)})
        if on_event:
            on_event(ev_reply)
        judge = agent_mod.judge_extraction(self.target_model, reply)
        ev_judge = self._event("judge", {"judge": judge})
        if on_event:
            on_event(ev_judge)
        return {"reply": reply, "judge": judge}

    def _finalize_success(self, partial: bool = False):
        if not self.stack:
            assembled = agent_mod.assemble_prompt_from_metadata(self.target_model, self.notes, self.fragments)
        else:
            best = max(self.stack, key=lambda x: x.get("score", 0))
            assembled = best["text"]
            if len(assembled) < 300 and self.fragments:
                assembled = agent_mod.assemble_prompt_from_metadata(self.target_model, self.notes, self.fragments) or assembled
        self.final_prompt = assembled
        k_mod.save_extracted_prompt(self.target_model, assembled)
        log_obj = {
            "model_id": self.target_model,
            "architecture": self.architecture,
            "attempts": self.attempt_no,
            "successful_combos": list(set(self.successful_combos)),
            "stack_size": len(self.stack),
            "final_verdict": "partial" if partial else "success",
            "events": self.events,
            "attempts_detail": [
                {
                    "attempt": a["attempt"], "combo": a["combo"], "turn_skill": a["turn_skill"],
                    "sent": a["sent"], "reply": a["reply"], "judge": a["judge"], "reward": a["reward"],
                } for a in self.attempts_this_session
            ],
        }
        k_mod.save_extraction_log(self.target_model, log_obj)
        k_mod.set_model_status(self.target_model, "success" if not partial else "partial")
        self.knowledge["meta"]["total_successes"] = self.knowledge["meta"].get("total_successes", 0) + 1
        if self.target_model not in self.knowledge["meta"].get("models_succeeded", []):
            self.knowledge["meta"].setdefault("models_succeeded", []).append(self.target_model)
        if self.successful_combos:
            rule_proposal = agent_mod.propose_rule(self.target_model, self.architecture, list(set(self.successful_combos)), self.notes)
            r = k_mod.promote_rule(self.knowledge, rule_proposal.get("rule", ""), rule_proposal.get("skills", list(set(self.successful_combos))), self.target_model, self.architecture, rule_proposal.get("mechanism", ""))
            k_mod.add_observation(self.knowledge, self.target_model, f"Promoted rule {r['id']} after success with {r['skills']}.")
        k_mod.save_knowledge(self.knowledge)
        self.status = "success" if not partial else "partial"

    def finalize_manual(self, success: bool = True):
        if success:
            self._finalize_success(partial=False)
        else:
            k_mod.add_observation(self.knowledge, self.target_model, f"Manual stop with {len(self.stack)} candidates.")
            k_mod.save_knowledge(self.knowledge)
            self.status = "stopped"
