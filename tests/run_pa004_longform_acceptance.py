"""Live-model segmented Chinese long-form test with durable SQLite checkpoints."""
from __future__ import annotations
import json, pathlib, sys, time, uuid, re
from datetime import datetime, timezone

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from runtime import Runtime, IncompleteGeneration, continuation_overlap
from store import Store

HOME=pathlib.Path(r"D:\PoJiaAI")
DATA=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/".pa003-cache"/"pa004-longform-data"
DATA.mkdir(parents=True,exist_ok=True)
store=Store(DATA);runtime=Runtime(HOME,HOME/"models"/"inkling2mini")
if runtime.status()!="ready":raise SystemExit("expected verified local inference service is not ready")
with __import__("urllib.request",fromlist=["urlopen"]).urlopen(runtime.base+"/props",timeout=3) as response:server_props=json.load(response)
if pathlib.Path(server_props.get("model_path","")).resolve()!=runtime.model_path.resolve():raise SystemExit("actual loaded model path does not match IQ2_M selection")
run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:10]
sid=store.new_session("PA-005 REV04 live segmented long-form")
plan=("规划一篇约2300个中文字符的分节文章，主题为‘家庭照片本地备份与校验’。分成5节，每节约450个汉字，语言简洁，不要声称已经执行任何操作。只返回5个简短小节标题，每个标题独占一行。")
store.begin_draft(sid,plan)
started=time.perf_counter();answers=[];events=[]

def generate(messages, limit=512):
    text="";t=time.perf_counter();error=None
    try:
        for piece in runtime.chat(messages,stream=True,max_tokens=limit,timeout=240):text+=piece
    except Exception as exc:error=f"{type(exc).__name__}: {exc}"
    return text,time.perf_counter()-t,error

outline,elapsed,error=generate([{"role":"user","content":plan}],256)
events.append({"phase":"outline","seconds":round(elapsed,3),"chars":len(outline),"error":error})
if error or not outline.strip():
    store.save_draft(sid,"","outline_failed")
else:
    store.save_draft(sid,outline,"generating");answers.append(outline)
    headings=[x.strip() for x in outline.splitlines() if x.strip()]
    if len(headings)<5:headings=[f"第{i}节" for i in range(1,6)]
    for i,heading in enumerate(headings[:5],1):
        # Keep each generation bounded to one paragraph; avoid feeding a growing article
        # back into the model, which caused long prefills and truncation on this GPU.
        parts=[];attempts=[];terminal_error=None
        for part in range(1,4):
            part_prompt=(f"写文章第{i}节：{heading}。只写四句中文，每句约30个汉字，合计约120字。"
                         "内容具体且不复述其他章节。四句话写完立即结束，不要标题或续写说明。")
            messages=runtime.build_context([{"role":"user","content":plan},
                    {"role":"assistant","content":outline},
                    {"role":"user","content":part_prompt}],token_budget=2048,output_tokens=256)
            current="\n\n".join(answers+(["".join(parts)] if parts else []))
            store.save_draft(sid,current+f"\n\n[{i}/5 段 {part}/3 生成中] ","generating")
            segment,elapsed,error=generate(messages,256)
            if segment:
                old="".join(parts);overlap=continuation_overlap(old,segment,minimum=24) if old else 0
                parts.append(segment[overlap:])
            attempts.append({"seconds":round(elapsed,3),"chars":len(segment),"error":error,
                             "recovered_length":bool(error and "length" in error.lower())})
            if error:
                terminal_error=error
                break
            if len(re.findall(r"[\u4e00-\u9fff]","".join(parts)))>=330:
                break
        section="".join(parts)
        section_chars=len(re.findall(r"[\u4e00-\u9fff]",section))
        if not terminal_error and section_chars<300:
            terminal_error=f"section_under_length:{section_chars}"
        events.append({"phase":f"section_{i}","attempts":attempts,"chars":len(section),"chinese_characters":section_chars,"error":terminal_error})
        if terminal_error or not section.strip():
            store.save_draft(sid,"\n\n".join(answers+([section] if section else [])),terminal_error or "empty_section")
            break
        answers.append(section)
        store.save_draft(sid,"\n\n".join(answers),"generating")
    else:
        article="\n\n".join(answers)
        chinese_chars=len(re.findall(r"[\u4e00-\u9fff]",article))
        if chinese_chars<2000:
            store.save_draft(sid,article,"under_length")
        else:
            store.finish_draft(sid,article)

draft=store.draft(sid);rows=store.messages(sid)
article_text=draft["content"] if draft else rows[-1]["content"] if len(rows)>1 else ""
result={"run_id":run_id,"model":pathlib.Path(server_props.get("model_path","")).name,"backend":"CUDA b12774","elapsed_seconds":round(time.perf_counter()-started,3),"section_events":events,
        "article_chars":len(article_text),"chinese_characters":len(re.findall(r"[\u4e00-\u9fff]",article_text)),
        "completed":draft is None and len(rows)>1,"draft_status":draft["status"] if draft else None,
        "checkpoint_persisted":bool(draft and Store(DATA).draft(sid)),"history_messages":len(rows)}
result["passed"]=bool(result["completed"] and result["chinese_characters"]>=2000 and result["history_messages"]==2 and all(not e["error"] for e in events))
out=DATA/f"pa005-rev04-longform-{run_id}.json";out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2));print("REPORT="+str(out))
if not result["passed"]:raise SystemExit(2)
