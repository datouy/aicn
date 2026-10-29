# -*- coding: utf-8 -*-
"""aicn Web 面板 —— 零依赖本地面板(启动:python -m aicn web)

面板直接复用 cli 的命令函数,与命令行行为完全一致。
不保存任何密钥:密钥只存在于浏览器与本次请求进程内存之间。
"""
from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import cli

HTML = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>aicn · Web 面板</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--dim:#8b949e;--acc:#58a6ff;--ok:#3fb950;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,"Segoe UI","Microsoft YaHei",sans-serif;padding:20px}
h1{font-size:20px;margin:0}.sub{color:var(--dim);font-size:12px;margin:4px 0 18px}a{color:var(--acc)}
.wrap{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.card h2{font-size:15px;margin:0 0 12px}
label{display:block;font-size:12px;color:var(--dim);margin:8px 0 4px}
input,select{width:100%;background:#0d1117;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:7px 9px;font-size:13px}
.row2{display:flex;gap:8px}.row2>*{flex:1}
button{background:#21262d;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:8px 14px;font-size:13px;cursor:pointer;margin-top:12px}
button:hover{border-color:var(--acc)}button.primary{background:rgba(88,166,255,.12);border-color:var(--acc)}
button.okbtn{background:rgba(63,185,80,.12);border-color:var(--ok);margin-left:8px}
pre,.out{background:#010409;border:1px solid var(--line);border-radius:8px;padding:12px;font:12.5px/1.5 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-all;max-height:360px;overflow:auto;margin:10px 0 0}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:10px}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left}th{color:var(--dim);font-weight:600}
.hint{color:var(--dim);font-size:12px;margin-top:8px}
.hidden{display:none}
</style></head><body>
<h1>aicn <span style="color:var(--acc)">Web 面板</span></h1>
<div class="sub">国产大模型一键接入 Codex / Claude Code / Cursor / Cline · 零依赖 · 端口 __PORT__ · 姊妹项目:<a href="__LLMBENCH_URL__" target="_blank">llmbench-cn 面板</a></div>
<div class="wrap">
<div class="card">
<h2>① 供应商 / 模型 / 价格</h2>
<button class="primary" onclick="loadList()">加载清单</button>
<div id="list-box"></div>
</div>
<div class="card">
<h2>② 连通测试</h2>
<label>供应商</label><select id="t-provider"></select>
<label>模型</label><div class="row2"><select id="t-model"></select><input id="t-model-custom" class="hidden" placeholder="输入模型名,如 deepseek-chat"></div>
<div class="row2"><div><label>协议</label><select id="t-protocol"><option value="chat">chat</option><option value="responses">responses</option><option value="anthropic">anthropic</option></select></div>
<div><label>API Key(可选)</label><input id="t-key" type="password" placeholder="仅本次请求内存"></div></div>
<label>覆盖 base_url(可选)</label><input id="t-base" placeholder="如 http://127.0.0.1:8799/v1">
<button class="primary" onclick="runTest()">开始测试</button>
<button class="okbtn" onclick="fillMock()">填入本地 mock 网关</button>
<div id="test-out"></div>
<div class="hint">密钥只进入本次请求内存,面板不保存、不落盘。</div>
</div>
<div class="card">
<h2>③ 生成接入配置</h2>
<label>目标工具</label><select id="g-tool"><option value="codex">Codex</option><option value="claude-code">Claude Code</option><option value="cursor">Cursor</option><option value="cline">Cline</option></select>
<label>供应商</label><select id="g-provider"></select>
<label>模型</label><div class="row2"><select id="g-model"></select><input id="g-model-custom" class="hidden" placeholder="输入模型名,如 qwen-plus"></div>
<label>API Key(仅 claude-code 会写入)</label><input id="g-key" type="password">
<label>wire_api(仅 Codex 生效)</label><select id="g-wire"><option value="responses">responses(默认,推荐)</option><option value="chat">chat(仅旧版)</option></select>
<label>覆盖 base_url(可选)</label><input id="g-base" placeholder="如 http://106.55.225.14/v1">
<label style="color:var(--fg)"><input type="checkbox" id="g-write" style="width:auto"> 真正写入配置文件(默认 dry-run,仅预览)</label>
<button class="primary" onclick="runGen()">生成配置</button>
<div id="gen-out"></div>
</div>
<div class="card">
<h2>④ 同步模型(/models)</h2>
<label>供应商</label><select id="s-provider"></select>
<label>覆盖 base_url(可选)</label><input id="s-base" placeholder="留空用该供应商默认地址">
<label>API Key(可选,缺省读环境变量)</label><input id="s-key" type="password">
<button class="primary" onclick="runSync()">拉取 /models 并更新数据文件</button>
<button class="okbtn" onclick="fillSyncMock()">填入本地 mock 网关</button>
<div id="sync-out"></div>
<div class="hint">向所选供应商的 <code>/models</code> 发起 GET 请求,把返回的模型写入 <code>~/.aicn/providers.json</code>(原价格信息按 id 保留,写入前自动备份 .bak)。<b>不会修改安装包或仓库里的 <code>aicn/data/providers.json</code></b> —— 同步结果只在你本机生效。大厂上新后在这里一键同步。</div>
</div>
<div class="card">
<h2>⑤ 环境体检 doctor</h2>
<button class="primary" onclick="runDoctor()">开始体检(探测 9 家公网端点)</button>
<div id="doctor-out"></div>
</div>
<div class="card">
<h2>⑥ 密钥环境变量命令</h2>
<label>供应商</label><select id="e-provider"></select>
<button onclick="runEnv()">查看命令</button>
<div id="env-out"></div>
</div>
</div>
<script>
const $=s=>document.getElementById(s);
async function api(path,body){const r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});return r.json()}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function render(el,obj){const pre=document.createElement('pre');let t='';if(obj.error)t+='错误: '+obj.error+'\n';if(obj.exit&&obj.exit!==0)t+='[退出码 '+obj.exit+']\n';if(obj.note)t+=obj.note+'\n';pre.textContent=t+(obj.out||'(无输出)');el.innerHTML='';el.appendChild(pre)}
let PROV={};
function fillProviderSelect(sel){const cats={};Object.keys(PROV).forEach(p=>{const c=PROV[p].category||'其他';(cats[c]=cats[c]||[]).push(p)});
const order=['国产直连','聚合平台','海外官方','自建网关','其他'];let h='';
order.filter(c=>cats[c]).forEach(c=>{h+='<optgroup label="'+esc(c)+'">'+cats[c].map(p=>'<option value="'+esc(p)+'">'+esc(PROV[p].cn||PROV[p].name||p)+'('+esc(p)+')</option>').join('')+'</optgroup>'});
sel.innerHTML=h}
function fillModelSelect(sel,pid){const p=PROV[pid]||{};const ms=p.models||[];const cur=(p.currency==='USD'?'$':'¥');
function price(v){return v==null?'':cur+(typeof v==='number'?v.toFixed(2):v)}
let h='<option value="">(默认第一个)</option>';
if(ms.length){const fams={};ms.forEach(m=>{const fam=(String(m.id).split(/[-\/.]/)[0]||'other').toUpperCase();(fams[fam]=fams[fam]||[]).push(m)});
const keys=Object.keys(fams);
if(keys.length>1){keys.forEach(f=>{h+='<optgroup label="'+esc(f)+'">'+fams[f].map(m=>'<option value="'+esc(m.id)+'">'+esc(m.id)+(m.input!=null?(' · '+esc(price(m.input))):'')+'</option>').join('')+'</optgroup>'})}
else{ms.forEach(m=>{h+='<option value="'+esc(m.id)+'">'+esc(m.id)+(m.input!=null?(' · '+esc(price(m.input))):'')+'</option>'})}}
h+='<option value="__custom__">✏️ 自定义…</option>';sel.innerHTML=h;syncCustomInput(sel)}
function syncCustomInput(sel){const inp=$(sel.id+'-custom');if(inp)inp.classList.toggle('hidden',sel.value!=='__custom__')}
function bindModel(selId,customId){const sel=$(selId);sel.addEventListener('change',()=>{$(customId).classList.toggle('hidden',sel.value!=='__custom__')})}
function modelValue(selId,customId){const sel=$(selId);return sel.value==='__custom__'?($(customId).value||null):(sel.value||null)}
async function loadProviders(){const r=await api('providers');PROV=r.providers||{};
['t-provider','g-provider','s-provider','e-provider'].forEach(id=>fillProviderSelect($(id)));
['t-provider','g-provider'].forEach(id=>{$(id).addEventListener('change',()=>{const p=$(id).value;fillModelSelect($(id==='t-provider'?'t-model':'g-model'),p)})});
fillModelSelect($('t-model'),$('t-provider').value);fillModelSelect($('g-model'),$('g-provider').value)}
async function loadList(){const r=await api('list',{});if(!r.ok){render($('list-box'),r);return}
const rows=(r.data&&r.data.rows)||[];let h='<table><tr><th>供应商</th><th>模型</th><th>输入/输出(1M)</th><th>上下文</th><th>协议</th><th>说明</th></tr>';
rows.forEach(x=>{h+='<tr><td>'+esc(x.provider)+'</td><td>'+esc(x.model)+'</td><td>'+esc(x.price)+'</td><td>'+esc(x.context)+'</td><td>'+esc(x.protocols)+'</td><td>'+esc(x.desc)+'</td></tr>'});
h+='</table><div class="hint">价格更新:'+esc((r.data&&r.data.price_updated)||'-')+' · 仅作参考,以官方定价页为准</div>';
$('list-box').innerHTML=h}
function fillMock(){$('t-provider').value='gateway';fillModelSelect($('t-model'),'gateway');$('t-key').value='mock-key';$('t-base').value='http://127.0.0.1:8799/v1'}
function fillSyncMock(){$('s-provider').value='gateway';$('s-base').value='http://127.0.0.1:8799/v1';$('s-key').value='mock-key'}
async function runTest(){$('test-out').innerHTML='<pre>运行中...</pre>';
const r=await api('test',{provider:$('t-provider').value,model:modelValue('t-model','t-model-custom'),key:$('t-key').value,protocol:$('t-protocol').value,base_url:$('t-base').value});render($('test-out'),r)}
async function runGen(){const r=await api('gen',{tool:$('g-tool').value,provider:$('g-provider').value,model:modelValue('g-model','g-model-custom'),key:$('g-key').value,wire_api:$('g-wire').value,base_url:$('g-base').value,write:$('g-write').checked});render($('gen-out'),r)}
async function runSync(){$('sync-out').innerHTML='<pre>运行中...</pre>';
const r=await api('sync',{provider:$('s-provider').value,base_url:$('s-base').value,key:$('s-key').value});
if(r.ok){let h='<pre>✓ 已写入用户数据文件(原文件备份 .bak)\n端点: '+esc(r.url)+'\n写入: '+esc(r.path||'')+'\n模型数: '+r.count+'\n新增: '+(r.added.length?r.added.map(esc).join(', '):'(无)')+'\n移除: '+(r.removed.length?r.removed.map(esc).join(', '):'(无)')+'</pre>';
$('sync-out').innerHTML=h;await loadProviders()}else{render($('sync-out'),r)}}
async function runDoctor(){$('doctor-out').innerHTML='<pre>运行中(约 10-30 秒)...</pre>';const r=await api('doctor',{});render($('doctor-out'),r)}
async function runEnv(){const r=await api('env',{provider:$('e-provider').value});render($('env-out'),r)}
bindModel('t-model','t-model-custom');bindModel('g-model','g-model-custom');
loadProviders();loadList();
</script></body></html>"""


def _run(fn, ns) -> dict:
    """在线程中执行 cli 命令函数，捕获异常与退出码。

    不使用 contextlib.redirect_stdout —— 那会改写进程级全局的 sys.stdout，
    在 ThreadingHTTPServer 的并发请求下会把 A 请求的输出（含密钥）串到 B 响应里。
    cli 的命令函数一律以返回值传递文本，副作用（写文件）由调用方处理。
    """
    box: dict = {}

    def worker():
        try:
            # 不要写成 `fn(ns) or ""`：空文本的 CommandOutput 会被当成假值，
            # 退化成普通 str 从而丢掉 exit_code（失败却返回 0）。
            result = fn(ns)
            box["out"] = result if result is not None else ""
            box["exit"] = getattr(box["out"], "exit_code", 0)
        except cli.AicnError as exc:
            box["error"] = str(exc)
            box["exit"] = exc.code
        except SystemExit as exc:
            box["exit"] = exc.code or 0
        except Exception as exc:
            box["error"] = "%s: %s" % (type(exc).__name__, exc)
            box["exit"] = 1

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(timeout=600)
    if th.is_alive():
        box["note"] = "任务仍在后台执行,超 600s 未返回。"
    out = str(box.get("out", ""))
    exit_code = box.get("exit", 0)
    return {"ok": box.get("error") is None and exit_code == 0,
            "exit": exit_code, "error": box.get("error", ""),
            "note": box.get("note", ""), "out": out.strip()}


def api_providers() -> dict:
    data = cli.load_providers()
    return {"ok": True, "providers": data["providers"],
            "price_updated": data.get("price_updated", "")}


def api_list(body: dict) -> dict:
    ns = argparse.Namespace(provider=body.get("provider") or None, json=True)
    res = _run(cli.cmd_list, ns)
    if res["ok"]:
        try:
            res["data"] = json.loads(res["out"])
            res["out"] = ""
        except Exception:
            pass
    return res


def api_test(body: dict) -> dict:
    ns = argparse.Namespace(provider=body.get("provider") or "",
                            model=body.get("model") or None,
                            key=body.get("key") or None,
                            protocol=body.get("protocol") or "chat",
                            base_url=body.get("base_url") or None)
    return _run(cli.cmd_test, ns)


def api_gen(body: dict) -> dict:
    ns = argparse.Namespace(tool=body.get("tool") or "codex",
                            provider=body.get("provider") or "",
                            model=body.get("model") or None,
                            key=body.get("key") or None,
                            write=bool(body.get("write")),
                            wire_api=body.get("wire_api") or None,
                            base_url=body.get("base_url") or None)
    return _run(cli.cmd_gen, ns)


def api_sync(body: dict, data_file=None) -> dict:
    """从供应商/网关的 /models 拉取模型列表并写入用户级数据文件。

    不再直接改包内 / 仓库里的 providers.json —— 那是 site-packages 或你的
    源码目录，写坏了会污染全局安装环境或误提交到 git。
    """
    pid = body.get("provider") or ""
    key = body.get("key") or ""
    try:
        res = cli.sync_models(pid, body.get("base_url") or None,
                              key or None,
                              Path(data_file) if data_file else None)
    except Exception as exc:
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    if not res["ok"]:
        return res
    return {"ok": True, "url": res["url"], "count": res["count"], "path": res["path"],
            "added": res["added"], "removed": res["removed"]}


def api_doctor(body: dict) -> dict:
    return _run(cli.cmd_doctor, argparse.Namespace())


def api_env(body: dict) -> dict:
    return _run(cli.cmd_env, argparse.Namespace(provider=body.get("provider") or ""))


API = {"list": api_list, "test": api_test, "gen": api_gen, "sync": api_sync,
       "doctor": api_doctor, "env": api_env}


class Handler(BaseHTTPRequestHandler):
    server_version = "aicn-web/" + cli.VERSION
    port = 8787
    llmbench_url = "http://127.0.0.1:8789/"

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else \
            json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = HTML.replace("__PORT__", str(self.port)) \
                       .replace("__LLMBENCH_URL__", self.llmbench_url)
            self._send(200, page, "text/html; charset=utf-8")
            return
        if self.path == "/api/providers":
            self._send(200, api_providers())
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        name = self.path[5:]
        if name == "providers":
            self._send(200, api_providers())
            return
        fn = API.get(name)
        if not fn:
            self._send(404, {"ok": False, "error": "unknown api: " + name})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._send(400, {"ok": False, "error": "bad json"})
            return
        try:
            self._send(200, fn(body))
        except Exception as exc:
            self._send(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})


def cmd_web(args: argparse.Namespace) -> int:
    Handler.port = args.port
    Handler.llmbench_url = getattr(args, "llmbench_url", None) or "http://127.0.0.1:8789/"
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://%s:%d/" % (args.host, srv.server_address[1])
    print("aicn Web 面板:%s(Ctrl+C 停止)" % url)
    if not args.no_open:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n面板已停止")
    finally:
        srv.server_close()
    return 0
