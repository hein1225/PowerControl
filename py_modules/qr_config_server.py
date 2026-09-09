"""
AI 模型配置「手机扫码填写」本地服务。

场景：掌机上输入端点 / 密钥 / 模型名很不便。此模块在用户点击「手机扫码填写」时
临时启动一个本地 HTTP 服务（仅对话框打开期间运行，关闭即停），提供一个手机可填的
Web 表单；手机与掌机处于同一局域网时扫码打开该表单，填写并提交后，服务端回调
save_cb 把配置写入 ai_tuner（与 set_ai_online RPC 同一条落盘路径）。

设计约束：
- 仅绑定本地网卡、仅对话框生命周期内运行；不做公网暴露。
- 表单为自包含 HTML（内联样式，无外部依赖），移动端友好。
- 不引入第三方依赖（标准库 http.server + socket）。
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

# 固定端口：手机会扫码访问此端口，固定后 URL 稳定、便于记忆与排错。
# 若该端口被占用（极少见），回退到随机端口以保证功能可用。
QR_PORT = 18769

FORM_HTML = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>PowerContorlAI 模型配置</title>
<style>
  body{margin:0;background:#0e1116;color:#e6e6e6;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:18px;}
  h2{font-size:18px;margin:0 0 4px;}
  .sub{font-size:12px;opacity:.6;margin:0 0 16px;}
  label{display:block;font-size:13px;margin:14px 0 6px;}
  input{width:100%;box-sizing:border-box;height:42px;border:1px solid #2a2f3a;border-radius:8px;background:#161b22;color:#fff;padding:0 12px;font-size:15px;}
  button{width:100%;height:48px;margin-top:22px;border:0;border-radius:10px;background:#1f6feb;color:#fff;font-size:16px;font-weight:600;}
  button:active{background:#1a5fc4;}
  .ok{margin-top:18px;padding:12px;border-radius:8px;background:#16351f;color:#7ee2a0;font-size:14px;text-align:center;}
  .err{margin-top:18px;padding:12px;border-radius:8px;background:#3a1d1d;color:#ff9b9b;font-size:14px;text-align:center;}
</style>
</head>
<body>
  <h2>PowerContorlAI · 远程 AI 模型</h2>
  <p class="sub">填写后保存，配置将直接写入掌机插件（本地加密保存）。</p>
  <form id="f">
    <label>在线模型端点 (OpenAI 兼容)</label>
    <input name="base_url" placeholder="https://api.openai.com/v1" value="${base_url}">
    <label>API 密钥</label>
    <input name="api_key" type="password" placeholder="sk-..." value="${api_key}">
    <label>模型名</label>
    <input name="model" placeholder="gpt-4o-mini / deepseek-chat / qwen …" value="${model}">
    <label>每轮采集时长（分钟）</label>
    <input name="collect_min" type="number" min="1" max="60" value="${collect_min}">
    <button type="submit">保存并测试连接</button>
  </form>
  <div id="msg"></div>
  <script>
    document.getElementById('f').addEventListener('submit', async function(e){
      e.preventDefault();
      var b=document.getElementById('f');
      var d={base_url:b.base_url.value.trim(), api_key:b.api_key.value, model:b.model.value.trim(), collect_min:parseInt(b.collect_min.value||'5',10)};
      var msg=document.getElementById('msg');
      if(!d.base_url||!d.api_key||!d.model){msg.className='err';msg.textContent='请填写端点、密钥与模型名';return;}
      msg.className='';msg.textContent='保存中…';
      try{
        var r=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
        var j=await r.json();
        if(j&&j.ok){msg.className='ok';msg.textContent='已保存 ✓ 可关闭此页面，回到掌机继续';}
        else{msg.className='err';msg.textContent='保存失败：'+(j&&j.error?j.error:'未知错误');}
      }catch(err){msg.className='err';msg.textContent='网络错误：'+err;}
    });
  </script>
</body>
</html>"""


def _html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class QRConfigServer:
    def __init__(
        self,
        save_cb: Callable[[str, str, str, int], bool],
        get_cfg_cb: Optional[Callable[[], dict]] = None,
    ):
        self._save_cb = save_cb
        self._get_cfg_cb = get_cfg_cb
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port = 0

    @staticmethod
    def lan_ip() -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()

    def _build_html(self) -> str:
        cfg: dict = {}
        try:
            if self._get_cfg_cb:
                cfg = self._get_cfg_cb() or {}
        except Exception:
            cfg = {}
        base = _html_escape(cfg.get("base_url", "") or "")
        key = _html_escape(cfg.get("api_key", "") or "")
        model = _html_escape(cfg.get("model", "") or "")
        collect_min = int((cfg.get("collect_sec") or 600) / 60)
        if collect_min < 1:
            collect_min = 1
        return FORM_HTML.replace("${base_url}", base).replace("${api_key}", key) \
            .replace("${model}", model).replace("${collect_min}", str(collect_min))

    def _make_handler(self):
        save_cb = self._save_cb
        build_html = self._build_html

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.split("?")[0] in ("/", "/index.html"):
                    html = build_html()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(html.encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path.split("?")[0] == "/save":
                    try:
                        n = int(self.headers.get("Content-Length", "0") or "0")
                        raw = self.rfile.read(n) if n > 0 else b"{}"
                        data = json.loads(raw or b"{}")
                        ok = save_cb(
                            str(data.get("base_url", "") or ""),
                            str(data.get("api_key", "") or ""),
                            str(data.get("model", "") or ""),
                            int(data.get("collect_min", 5) or 5) * 60,
                        )
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": bool(ok)}).encode("utf-8"))
                    except Exception as e:  # noqa: BLE001
                        self.send_response(500)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):  # silence
                return

        return _Handler

    def start(self) -> str:
        if self._server:
            return self.url()
        HTTPServer.allow_reuse_address = True
        self._server = None
        for port in (QR_PORT, 0):
            try:
                self._server = HTTPServer(("0.0.0.0", port), self._make_handler())
                self._port = port
                break
            except OSError:
                self._server = None
        if not self._server:
            return ""
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url()

    def url(self) -> str:
        return "http://{}:{}/".format(self.lan_ip(), self._port)

    def stop(self):
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
            self._thread = None

    @property
    def running(self) -> bool:
        return self._server is not None
