"""Exercise a live streamed response, deliberate client interruption and recovery."""
from __future__ import annotations
import json, pathlib, sys, threading, time
from pa005_acceptance import new_run,require_model,write_report

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from runtime import Runtime
from store import Store

HOME=pathlib.Path(r"D:\PoJiaAI")
DATA=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/".pa003-cache"/"pa004-interrupt-data"
runtime=Runtime(HOME,HOME/"models"/"inkling2mini")
if runtime.status()!="ready":raise SystemExit("expected verified local model service not ready")
expected_model=require_model()
with __import__("urllib.request",fromlist=["urlopen"]).urlopen(runtime.base+"/props",timeout=3) as response:
    props=json.load(response)
if pathlib.Path(props.get("model_path","")).resolve()!=runtime.model_path.resolve():raise SystemExit("actual loaded model path does not match selected IQ2_M model")
run_id,report=new_run("interrupt-recovery")
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
interrupt_seconds=time.perf_counter()-started
if not partial:raise SystemExit("model produced no visible partial text; interruption was not exercised")
store.save_draft(sid,partial,"cancelled")
store=Store(DATA) # close/reopen SQLite to exercise restart recovery
checkpoint=store.draft(sid)
if checkpoint is None or checkpoint["content"]!=partial:raise SystemExit("checkpoint failed restart persistence verification")
history=[dict(x) for x in store.messages(sid)]
history.extend([{"role":"assistant","content":partial},
                {"role":"user","content":"请从上次中断的末尾继续，只生成后续内容，不要重复已有文本。"}])
continuation="";resume_start=time.perf_counter();resume_error=None;resume_events=[]
for attempt in range(3):
    current=partial+continuation
    if attempt==0:
        resume_prompt="请从上次中断的末尾继续，只生成后续内容，不要重复已有文本。"
        limit=512
    else:
        resume_prompt="请为上文补写一个简短结语，自然结束全文，不要重复已有内容。"
        limit=256
    resume_history=[dict(x) for x in store.messages(sid)]
    resume_history.extend([{"role":"assistant","content":current},
                           {"role":"user","content":resume_prompt}])
    segment="";segment_error=None;segment_start=time.perf_counter()
    try:
        for piece in runtime.chat(resume_history,stream=True,max_tokens=limit,timeout=240):
            segment+=piece;store.save_draft(sid,current+segment,"generating")
    except Exception as exc:segment_error=f"{type(exc).__name__}: {exc}"
    continuation+=segment
    resume_events.append({"attempt":attempt+1,"seconds":round(time.perf_counter()-segment_start,3),
                          "chars":len(segment),"error":segment_error})
    if segment_error is None and segment.strip():
        resume_error=None
        break
    resume_error=segment_error or "empty_continuation"
    if segment_error and "length" not in segment_error.lower():
        break
if continuation and resume_error is None:
    store.finish_draft(sid,partial+continuation)
else:
    store.save_draft(sid,partial+continuation,resume_error or "empty_continuation")
store=Store(DATA);rows=store.messages(sid);draft=store.draft(sid)
result={"run_id":run_id,"model":expected_model,"session_id":sid,"initial_seconds":round(interrupt_seconds,3),
        "partial_chars":len(partial),"restart_checkpoint_matches":bool(checkpoint and checkpoint["content"]==partial),
        "continuation_seconds":round(time.perf_counter()-resume_start,3),"continuation_chars":len(continuation),
        "continuation_events":resume_events,
        "initial_error":error,"continuation_error":resume_error,"complete_history_messages":len(rows),
        "draft_status":draft["status"] if draft else None,"finished_exactly_once":draft is None and len(rows)==2,
        "answer_prefix_preserved":bool(rows and rows[-1]["content"].startswith(partial))}
out=report
write_report(out,result)
print(json.dumps(result,ensure_ascii=False,indent=2));print("REPORT="+str(out))
if not result["restart_checkpoint_matches"] or not result["finished_exactly_once"] or not result["answer_prefix_preserved"]:
    raise SystemExit(2)
