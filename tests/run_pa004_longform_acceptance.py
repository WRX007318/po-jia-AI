"""Live-model segmented Chinese long-form test with durable SQLite checkpoints."""
from __future__ import annotations
import json, pathlib, sys, time

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from runtime import Runtime, IncompleteGeneration, build_context
from store import Store

HOME=pathlib.Path(r"D:\PoJiaAI")
DATA=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/".pa003-cache"/"pa004-longform-data"
store=Store(DATA);runtime=Runtime(HOME,HOME/"models"/"inkling2mini")
if runtime.status()!="ready":raise SystemExit("expected verified local inference service is not ready")
sid=store.new_session("PA-004 live segmented long-form acceptance")
plan=("请先规划一篇约2000个中文字符的分节文章，主题为‘家庭照片本地备份与校验’。分成4节，每节约500个汉字，语言简洁，不要声称已经执行任何操作。只返回4个简短小节标题，每个标题独占一行。")
store.begin_draft(sid,plan)
started=time.perf_counter();answers=[];events=[]

def generate(messages, limit=512):
    text="";t=time.perf_counter();error=None
    try:
        for piece in runtime.chat(messages,stream=True,max_tokens=limit,timeout=240):text+=piece
    except Exception as exc:error=f"{type(exc).__name__}: {exc}"
    return text,time.perf_counter()-t,error

outline,elapsed,error=generate([{"role":"user","content":plan}],128)
events.append({"phase":"outline","seconds":round(elapsed,3),"chars":len(outline),"error":error})
if error or not outline.strip():
    store.save_draft(sid,"","outline_failed")
else:
    store.save_draft(sid,outline,"generating");answers.append(outline)
    headings=[x.strip() for x in outline.splitlines() if x.strip()]
    if len(headings)<4:headings=[f"第{i}节" for i in range(1,5)]
    for i,heading in enumerate(headings[:4],1):
        prompt=f"继续写文章第{i}节：{heading}\n要求约500个中文字符，正文具体、可操作；只输出本节标题和正文，不重复其他章节。"
        history=store.messages(sid)
        messages=build_context([dict(m) for m in history]+[{"role":"assistant","content":"\n".join(answers)},
                                 {"role":"user","content":prompt}],12000)
        store.save_draft(sid,"\n\n".join(answers)+f"\n\n[{i}/4 生成中] ","generating")
        segment,elapsed,error=generate(messages,512)
        events.append({"phase":f"section_{i}","seconds":round(elapsed,3),"chars":len(segment),"error":error})
        if error or not segment.strip():
            store.save_draft(sid,"\n\n".join(answers+([segment] if segment else [])),error or "empty_section")
            break
        answers.append(segment)
        store.save_draft(sid,"\n\n".join(answers),"generating")
    else:
        article="\n\n".join(answers)
        if len(article)<1800:
            store.save_draft(sid,article,"under_length")
        else:
            store.finish_draft(sid,article)

draft=store.draft(sid);rows=store.messages(sid)
result={"model":"IQ3_S","backend":"verified local CUDA service","session_id":sid,
        "elapsed_seconds":round(time.perf_counter()-started,3),"section_events":events,
        "article_chars":len(draft["content"] if draft else rows[-1]["content"] if len(rows)>1 else ""),
        "completed":draft is None and len(rows)>1,"draft_status":draft["status"] if draft else None,
        "checkpoint_persisted":bool(draft and Store(DATA).draft(sid)),"history_messages":len(rows)}
out=DATA/"pa004-longform-result.json";out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2));print("REPORT="+str(out))
if not result["completed"]:raise SystemExit(2)
