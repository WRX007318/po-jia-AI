"""Exercise a live streamed response, deliberate client interruption and recovery."""
from __future__ import annotations
import json, pathlib, sys, threading, time

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from runtime import Runtime
from store import Store

HOME=pathlib.Path(r"D:\PoJiaAI")
DATA=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/".pa003-cache"/"pa004-interrupt-data"
runtime=Runtime(HOME,HOME/"models"/"inkling2mini")
if runtime.status()!="ready":raise SystemExit("expected verified local model service not ready")
store=Store(DATA);sid=store.new_session("PA-004 live interrupt recovery")
prompt="请用中文分节写一篇关于本地备份策略的长文，至少1200字。先开始回答。"
store.begin_draft(sid,prompt);received=[];started=time.perf_counter();error=None
stream=runtime.chat([{"role":"user","content":prompt}],stream=True,max_tokens=2048,timeout=240)
try:
    for piece in stream:
        received.append(piece);store.save_draft(sid,"".join(received),"generating")
        if len("".join(received))>=240:
            stream.close();break
except Exception as exc:error=f"{type(exc).__name__}: {exc}"
partial="".join(received)
if not partial:raise SystemExit("model produced no visible partial text; interruption was not exercised")
store.save_draft(sid,partial,"cancelled")
store=Store(DATA) # close/reopen SQLite to exercise restart recovery
checkpoint=store.draft(sid)
if checkpoint is None or checkpoint["content"]!=partial:raise SystemExit("checkpoint failed restart persistence verification")
history=[dict(x) for x in store.messages(sid)]
history.extend([{"role":"assistant","content":partial},
                {"role":"user","content":"请从上次中断的末尾继续，只生成后续内容，不要重复已有文本。"}])
continuation="";resume_start=time.perf_counter();resume_error=None
try:
    for piece in runtime.chat(history,stream=True,max_tokens=512,timeout=240):
        continuation+=piece;store.save_draft(sid,partial+continuation,"generating")
except Exception as exc:resume_error=f"{type(exc).__name__}: {exc}"
if continuation and not resume_error:
    store.finish_draft(sid,partial+continuation)
else:
    store.save_draft(sid,partial+continuation,resume_error or "empty_continuation")
store=Store(DATA);rows=store.messages(sid);draft=store.draft(sid)
result={"session_id":sid,"initial_seconds":round(time.perf_counter()-started,3),
        "partial_chars":len(partial),"restart_checkpoint_matches":bool(checkpoint and checkpoint["content"]==partial),
        "continuation_seconds":round(time.perf_counter()-resume_start,3),"continuation_chars":len(continuation),
        "initial_error":error,"continuation_error":resume_error,"complete_history_messages":len(rows),
        "draft_status":draft["status"] if draft else None,"finished_exactly_once":draft is None and len(rows)==2,
        "answer_prefix_preserved":bool(rows and rows[-1]["content"].startswith(partial))}
out=DATA/"pa004-interrupt-recovery.json";out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2));print("REPORT="+str(out))
if not result["restart_checkpoint_matches"]:raise SystemExit(2)
