import json
import os
import csv
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs" / "evolving"
KNOWLEDGE_PATH = DATA_DIR / "extraction_knowledge.json"
T1_CSV = DATA_DIR / "t1.csv"
T1_DIR = DATA_DIR / "T1"
ARCHIVE_DIR = ROOT / "archive"


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    T1_DIR.mkdir(parents=True, exist_ok=True)


def default_knowledge() -> Dict:
    return {
        "meta": {
            "total_attempts": 0,
            "total_successes": 0,
            "models_attempted": [],
            "models_succeeded": [],
        },
        "exploration_policy": {
            "ucb_constant": 1.414,
            "min_visits_before_novel": 3,
            "exploration_budget_per_model": 100,
            "formula": "UCB(s) = avg_reward(s) + c * sqrt(ln(N+1) / n(s))",
            "agent_model": "gpt-5.6-sol",
            "provider": "llmapi.ai",
        },
        "skill_stats": {},
        "rules": {"extrinsic": []},
        "model_observations": {},
    }


def load_knowledge() -> Dict:
    ensure_dirs()
    if not KNOWLEDGE_PATH.exists():
        k = default_knowledge()
        save_knowledge(k)
        return k
    try:
        with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
            k = json.load(f)
    except Exception:
        k = default_knowledge()
    base = default_knowledge()
    for kk, vv in base.items():
        if kk not in k:
            k[kk] = vv
    return k


def save_knowledge(k: Dict):
    ensure_dirs()
    tmp = KNOWLEDGE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(k, f, indent=2, ensure_ascii=False)
    tmp.replace(KNOWLEDGE_PATH)


def load_models() -> List[Dict]:
    ensure_dirs()
    if not T1_CSV.exists():
        return []
    rows = []
    with open(T1_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def save_models(rows: List[Dict]):
    ensure_dirs()
    fieldnames = ["order", "model_id", "release_date", "architecture", "status"]
    tmp = T1_CSV.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    tmp.replace(T1_CSV)


def upsert_model(model_id: str, architecture: str = "unknown") -> Dict:
    rows = load_models()
    for r in rows:
        if r.get("model_id") == model_id:
            if not r.get("architecture") or r.get("architecture") == "unknown":
                r["architecture"] = architecture
            return r
    order = len(rows)
    row = {
        "order": str(order),
        "model_id": model_id,
        "release_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "architecture": architecture,
        "status": "pending",
    }
    rows.append(row)
    save_models(rows)
    return row


def set_model_status(model_id: str, status: str):
    rows = load_models()
    for r in rows:
        if r.get("model_id") == model_id:
            r["status"] = status
    save_models(rows)


def architecture_of(model_id: str) -> str:
    rows = load_models()
    for r in rows:
        if r.get("model_id") == model_id:
            arch = r.get("architecture")
            if arch and arch != "unknown":
                return arch
    if model_id.startswith("openai/") or model_id.startswith("gpt"):
        return "gpt"
    if model_id.startswith("anthropic/") or model_id.startswith("claude"):
        return "claude"
    if model_id.startswith("google/") or "gemini" in model_id:
        return "gemini"
    if model_id.startswith("x-ai/") or "grok" in model_id:
        return "grok"
    if model_id.startswith("meta-llama/") or "llama" in model_id:
        return "llama"
    if model_id.startswith("mistralai/") or "mistral" in model_id:
        return "mistral"
    if "deepseek" in model_id:
        return "deepseek"
    if "qwen" in model_id:
        return "qwen"
    return "unknown"


def model_dir(model_id: str) -> Path:
    safe = model_id.replace("/", "_").replace("\\", "_")
    d = T1_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir(model_id: str) -> Path:
    safe = model_id.replace("/", "_").replace("\\", "_")
    d = LOGS_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def attempt_count(model_id: str) -> int:
    d = log_dir(model_id)
    return len([p for p in d.glob("*.json") if "_current" not in p.name])


def save_extracted_prompt(model_id: str, prompt_text: str):
    md = model_dir(model_id)
    (md / "system_prompt.md").write_text(prompt_text or "", encoding="utf-8")


def save_extraction_log(model_id: str, log_obj: Dict):
    md = model_dir(model_id)
    (md / "extraction_log.json").write_text(json.dumps(log_obj, indent=2, ensure_ascii=False), encoding="utf-8")


def write_attempt_log(model_id: str, attempt_no: int, combo: str, conversation: List[Dict], reward: float, score: float, success: bool, meta_extra: Optional[Dict] = None) -> Path:
    d = log_dir(model_id)
    ts = datetime.utcnow().strftime("%m%d_%H%M%S")
    safe_combo = combo.replace("/", "_")
    name = f"{attempt_no:03d}_{ts}_{safe_combo}.json"
    payload = {
        "meta": {
            "phase": "evolving",
            "model_id": model_id,
            "attempt": attempt_no,
            "skill_combo": combo,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
        "conversation": conversation,
        "metrics": {
            "reward": reward,
            "score": score,
            "success": bool(success),
        },
    }
    if meta_extra:
        payload["meta"].update(meta_extra)
    p = d / name
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def read_extracted_prompt(model_id: str) -> str:
    md = model_dir(model_id)
    p = md / "system_prompt.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def rules_for_architecture(k: Dict, arch: str) -> List[Dict]:
    out = []
    for r in k.get("rules", {}).get("extrinsic", []):
        if r.get("architecture") == arch:
            out.append(r)
    return out


def promote_rule(k: Dict, rule_text: str, skills: List[str], model_id: str, arch: str, mechanism: str = "") -> Dict:
    existing = k.get("rules", {}).get("extrinsic", [])
    nid = f"E{len(existing)+1}"
    rule_obj = {
        "id": nid,
        "rule": rule_text,
        "skills": skills,
        "scope": f"{arch}/*" if arch != "unknown" else "*",
        "architecture": arch,
        "learned_from": [model_id],
        "failed_on": [],
        "confidence": "medium",
        "mechanism": mechanism,
    }
    existing.append(rule_obj)
    k["rules"]["extrinsic"] = existing
    return rule_obj


def validate_rule(k: Dict, rule_id: str, model_id: str):
    for r in k.get("rules", {}).get("extrinsic", []):
        if r.get("id") == rule_id:
            if model_id not in r.get("learned_from", []):
                r.setdefault("learned_from", []).append(model_id)
            if len(r.get("learned_from", [])) >= 2:
                r["confidence"] = "high"


def add_observation(k: Dict, model_id: str, note: str):
    obs = k.setdefault("model_observations", {})
    obs.setdefault(model_id, []).append({
        "ts": datetime.utcnow().isoformat() + "Z",
        "note": note,
    })


def archive_experiment() -> str:
    ensure_dirs()
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    existing = [p.name for p in ARCHIVE_DIR.iterdir() if p.is_dir()]
    n = 1
    while True:
        name = datetime.utcnow().strftime("%Y_%m_%d") + f"_exp{n}"
        if name not in existing:
            break
        n += 1
    target = ARCHIVE_DIR / name
    target.mkdir(parents=True, exist_ok=True)
    if T1_DIR.exists():
        shutil.copytree(T1_DIR, target / "T1", dirs_exist_ok=True)
    if LOGS_DIR.exists():
        shutil.copytree(LOGS_DIR, target / "evolving", dirs_exist_ok=True)
    if KNOWLEDGE_PATH.exists():
        shutil.copy2(KNOWLEDGE_PATH, target / "extraction_knowledge.json")
    if T1_CSV.exists():
        shutil.copy2(T1_CSV, target / "t1.csv")
    k = default_knowledge()
    save_knowledge(k)
    if T1_DIR.exists():
        shutil.rmtree(T1_DIR, ignore_errors=True)
    if LOGS_DIR.exists():
        shutil.rmtree(LOGS_DIR, ignore_errors=True)
    T1_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_models()
    for r in rows:
        r["status"] = "pending"
    save_models(rows)
    return name


def add_models_from_list(models: List[Dict]):
    ensure_dirs()
    rows = load_models()
    existing = {r.get("model_id") for r in rows}
    order = len(rows)
    for m in models:
        mid = m.get("model_id")
        if not mid or mid in existing:
            continue
        rows.append({
            "order": str(order),
            "model_id": mid,
            "release_date": m.get("release_date") or datetime.utcnow().strftime("%Y-%m-%d"),
            "architecture": m.get("architecture") or architecture_of(mid),
            "status": "pending",
        })
        existing.add(mid)
        order += 1
    save_models(rows)
