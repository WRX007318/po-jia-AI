"""Live model + PA-004 runtime/store acceptance on an isolated SQLite database."""
from __future__ import annotations
import json, pathlib, sys, time
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"app"))
from runtime import Runtime, build_context
from store import Store

HOME=pathlib.Path(r"D:\PoJiaAI")
DATA=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/".pa003-cache"/"pa004-live-data"
store=Store(DATA); runtime=Runtime(HOME,HOME/"models"/"inkling2mini")
if runtime.status()!="ready": raise SystemExit("CUDA-backed local model not ready at expected model path")
sid=store.new_session("PA-004 live 20-turn acceptance")
turns=[
("固定事实：测试暗号是青松731。请回复已记住。","已记住"),
("第2轮：用一句话解释显存。","显存"),
("第3轮：给出一个安全的Python变量名示例。",""),
("第4轮：用一句话解释SQLite。",""),
("第5轮：中文回答，2+3等于几？","5"),
("第6轮：列出两个文件校验用途。",""),
("第7轮：说出一个图像格式。",""),
("第8轮：用一句话解释HTTP。",""),
("第9轮：返回一个JSON对象，字段ok为true。",""),
("第10轮：中文回答，今天的测试模型是本地模型吗？",""),
("第11轮：给出一个列表常见用途。",""),
("第12轮：一句话说明上下文窗口。",""),
("第13轮：说出一个数据库主键作用。",""),
("第14轮：1分钟有多少秒？","60"),
("第15轮：说出一个可逆文件操作。",""),
("第16轮：视觉识别通常输出哪两类信息？",""),
("第17轮：一句话说明推理速度单位tok/s。",""),
("第18轮：列出一个安全测试边界。",""),
("第19轮：请用中文简短回答。",""),
("第20轮：回忆第1轮的测试暗号。","青松731"),
]
records=[]; history=[]
for i,(prompt,expected) in enumerate(turns,1):
    # Exercise the same durable draft lifecycle used by the desktop chat UI.
    store.begin_draft(sid,prompt); history.append({"role":"user","content":prompt})
    start=time.perf_counter(); error=None; answer=""
    try: answer=runtime.chat(build_context(history,12000),timeout=240,max_tokens=192)
    except Exception as exc: error=f"{type(exc).__name__}: {exc}"
    elapsed=time.perf_counter()-start
    if answer:
        store.save_draft(sid,answer,"generating")
        store.finish_draft(sid,answer);history.append({"role":"assistant","content":answer})
    else:
        # Keep the failed request as a resumable checkpoint, then reopen the
        # store to model app restart and verify user text/checkpoint survive.
        store.save_draft(sid,"", "failed")
        store=Store(DATA)
        assert store.draft(sid) is not None
        assert store.messages(sid)[-1]["content"] == prompt
    records.append({"turn":i,"seconds":round(elapsed,3),"answer_chars":len(answer),"expected_marker":expected,"marker_present":(expected in answer if expected else None),"error":error,"answer":answer})
    print(json.dumps(records[-1],ensure_ascii=False),flush=True)
    if error: break
history_rows=store.messages(sid)
result={"run":"live-model","model":"IQ3_S","backend":"CUDA b12774","session_id":sid,"turns_requested":20,"turns_completed":len([r for r in records if not r['error']]),"history_messages":len(history_rows),"draft_after_run":bool(store.draft(sid)),"history_matches_completed":len(history_rows)==sum(1 for r in records if not r['error'])*2,"turn_results":records}
out=DATA/"pa004-live-20-turns.json";out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");print("REPORT="+str(out));
