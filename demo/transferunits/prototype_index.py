"""PROTOTYPE — throwaway. Delete me when #68 closes.

The question this answers: what does the Launcher's index page look like, and how does it
behave?

Run it, hover it, click it::

    python demo/transferunits/prototype_index.py

It opens on http://127.0.0.1:8812/. No factory runs behind it. The state is a fake, and the
black bar drives it. The layout, the teaching layer and the state colors are the only things
under test.

The page is a **live topology picture**, not a process table. Etienne chose that on #68,
against a factory directory and against a process table. Every box is a participant, every
arrow is a link between two participants, and both carry a source file that a reader opens.

The Launcher itself is **not** a box. It sits in the header, outside the picture, because
ADR 0029 keeps it outside the semantic world.

Nothing here is production code. The real page is the build ticket this prototype writes.
"""

from __future__ import annotations

import copy
import json
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# --- The teaching layer ---------------------------------------------------------------- #
#
# One entry for each box and each arrow. `file` names a BACKEND source file, never a frontend
# one (ADR 0029). A test asserts that every path here exists on disk, so the page stays honest
# when a file moves.

TEACH = {
    "plc": {
        "title": "The mock PLC, and the panel it serves",
        "what": "It speaks MQTT, and it knows nothing about the graph, the ontology or the "
        "middleware. That asymmetry is the point of the demonstration. Its panel acts on "
        "the device directly.",
        "file": "demo/transferunits/plc/transfer_unit.py",
    },
    "middleware": {
        "title": "One middleware instance, for one unit",
        "what": "It reads its unit out of the graph and builds its connectors from what it "
        "finds there. No topic and no address is written in its code.",
        "file": "src/kapps_semantic_middleware/middleware.py",
    },
    "controller": {
        "title": "The control station",
        "what": "It lists every resource it finds in the graph, and it drives any of them. "
        "No endpoint is configured into it.",
        "file": "src/kapps_semantic_middleware/rest_router.py",
    },
    "broker": {
        "title": "The MQTT broker",
        "what": "The Launcher starts one when no broker listens, so the demonstration runs "
        "on a bare checkout.",
        "file": "src/kapps_semantic_middleware/connectors/mqtt_binding.py",
    },
    "graph": {
        "title": "The knowledge graph",
        "what": "It holds the units, their parameters, the address of every topic and the "
        "address of every service. It is the only thing the controller reads.",
        "file": "src/kapps_semantic_middleware/registration.py",
    },
    "launcher": {
        "title": "The Launcher",
        "what": "It seeds the graph and it starts every process on this page. It never "
        "appears in the graph, because nobody dispatches an Operation to bolt a conveyor to "
        "the floor (ADR 0029).",
        "file": "demo/transferunits/launcher.py",
    },
    "arrow-plc-broker": {
        "title": "The device publishes",
        "what": "The PLC publishes four values and subscribes to two setpoints. The unit "
        "index is the first segment of every topic.",
        "file": "demo/transferunits/plc/transfer_unit.py",
    },
    "arrow-broker-mw": {
        "title": "The middleware subscribes",
        "what": "The middleware subscribes to the same topics. It learned every one of them "
        "from the graph.",
        "file": "src/kapps_semantic_middleware/connectors/wiring.py",
    },
    "arrow-mw-graph": {
        "title": "The middleware reads and registers",
        "what": "It reads its unit from the graph at startup. It then registers its own "
        "Service and writes its address there.",
        "file": "src/kapps_semantic_middleware/registration.py",
    },
    "arrow-graph-ctrl": {
        "title": "The controller discovers",
        "what": "The controller finds the units here, and it finds their addresses here. "
        "This arrow is the reason no endpoint is configured into it.",
        "file": "src/kapps_semantic_middleware/registration.py",
    },
    "arrow-ctrl-mw": {
        "title": "The controller drives a unit",
        "what": "It sets a speed over REST, at an address it read from the graph. One "
        "parameter has one address.",
        "file": "src/kapps_semantic_middleware/rest_router.py",
    },
}

# Where the Launcher learned an address. The page marks every one of them.
SOURCES = {
    "pipe": "The Launcher read this address from one line of the process stdout. A PLC holds "
    "no graph credentials, so it cannot announce itself any other way.",
    "graph": "The Launcher read this address from svc:address in the knowledge graph. The "
    "process wrote it there itself, when it registered its Service.",
    "flag": "The Launcher chose this address, and it passed the address as a command-line "
    "flag.",
    "env": "This address comes from the GRAPHDB environment variables.",
}


def fresh_state() -> dict:
    return {
        "graph": {"state": "live", "address": "graphdb:7200/kapps", "source": "env"},
        "broker": {"state": "live", "address": "127.0.0.1:1883", "source": "flag"},
        "launcher": {"state": "live", "address": "127.0.0.1:8080", "source": "flag"},
        "controller": {
            "state": "live",
            "address": "127.0.0.1:8990",
            "source": "graph",
            "pid": 4816,
        },
        "unit": [
            _unit(1, 4812, "127.0.0.1:8123", 4813, "127.0.0.1:8991"),
            _unit(2, 4814, "127.0.0.1:8125", 4815, None, middleware_state="starting"),
        ],
    }


def _unit(index, plc_pid, plc_address, mw_pid, mw_address, middleware_state="live"):
    return {
        "index": index,
        "plc": {
            "state": "live",
            "address": plc_address,
            "source": "pipe",
            "pid": plc_pid,
        },
        "middleware": {
            "state": middleware_state,
            "address": mw_address,
            "source": "graph",
            "pid": mw_pid,
        },
    }


state = fresh_state()
app = FastAPI()


@app.get("/api/state")
async def api_state() -> JSONResponse:
    return JSONResponse(state)


@app.post("/api/stop/{index}")
async def stop_unit(index: int) -> JSONResponse:
    for unit in state["unit"]:
        if unit["index"] == index:
            for part in ("plc", "middleware"):
                unit[part]["state"] = "stopped"
                unit[part]["address"] = None
    return JSONResponse(state)


# PROTOTYPE ONLY — the black bar drives the fake through its states.
@app.post("/api/prototype/{name}")
async def scene(name: str) -> JSONResponse:
    global state
    state = fresh_state()
    if name == "starting":
        for unit in state["unit"]:
            for part in ("plc", "middleware"):
                unit[part]["state"] = "starting"
                unit[part]["address"] = None
        state["controller"]["state"] = "starting"
        state["controller"]["address"] = None
    elif name == "failed":
        state["unit"][1]["middleware"]["state"] = "failed"
        state["unit"][1]["middleware"]["address"] = None
    elif name == "four":
        template = state["unit"][0]
        for index in (3, 4):
            extra = copy.deepcopy(template)
            extra["index"] = index
            extra["plc"]["address"] = f"127.0.0.1:81{index}0"
            extra["middleware"]["address"] = f"127.0.0.1:899{index}"
            state["unit"].append(extra)
    return JSONResponse(state)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    page = PAGE.replace("__TEACH__", json.dumps(TEACH))
    return HTMLResponse(page.replace("__SOURCES__", json.dumps(SOURCES)))


PAGE = """
<!doctype html>
<meta charset="utf-8">
<title>Factory — the Launcher</title>
<style>
  :root { --ink:#1c1c1c; --muted:#6b6b6b; --line:#d5d5d2; --paper:#fff; --wire:#b4b4ae;
          --live:#2e7d32; --starting:#b26a00; --failed:#c62828; --stopped:#8a8a8a;
          --bar-line:#555; }
  body { font:15px/1.5 system-ui,sans-serif; color:var(--ink); margin:0;
         background:#f7f7f5; padding:20px 20px 190px }
  header { max-width:1180px; margin:0 auto 6px; display:flex; align-items:baseline;
           gap:14px; flex-wrap:wrap }
  h1 { font-size:20px; margin:0 }
  .sub { color:var(--muted); font-size:13px; margin:4px auto 16px; max-width:1180px }
  .chip { font-size:12px; border:1px dashed var(--line); border-radius:14px;
          padding:2px 11px; color:var(--muted); background:#fff; cursor:help }
  .chip b { color:var(--ink); font-weight:600 }
  .stage { max-width:1180px; margin:0 auto; position:relative }
  svg.wires { position:absolute; left:0; top:0; width:100%; pointer-events:none; z-index:0 }
  svg.wires path { stroke:var(--wire); stroke-width:2; fill:none }
  svg.wires path.hot { stroke:var(--ink); stroke-width:3 }
  .layer { display:grid; justify-items:center; align-items:start; gap:20px;
           margin-bottom:52px; position:relative }
  .layer.one { grid-template-columns:1fr }
  .box { background:var(--paper); border:1px solid var(--line); border-radius:8px;
         padding:10px 13px; width:196px; position:relative; z-index:1 }
  .box.wide { width:330px }
  .box.hot { border-color:var(--ink); box-shadow:0 0 0 3px rgba(0,0,0,.05) }
  .box h2 { font-size:13px; margin:0 0 5px }
  .dot { width:9px; height:9px; border-radius:50%; display:inline-block; margin-right:6px }
  .live .dot { background:var(--live) }
  .starting .dot { background:var(--starting) }
  .failed .dot { background:var(--failed) }
  .stopped .dot { background:var(--stopped) }
  .state { font-size:12px; color:var(--muted) }
  .failed .state { color:var(--failed); font-weight:600 }
  .addr { font:12px/1.7 ui-monospace,monospace; margin-top:3px }
  .addr a { color:#0b5cad; text-decoration:none }
  .addr a:hover { text-decoration:underline }
  .none { color:var(--stopped) }
  .src { font-size:10px; border:1px solid var(--line); border-radius:3px; padding:0 4px;
         color:var(--muted); margin-left:5px; cursor:help }
  .unit-head { font-size:12px; color:var(--muted); margin-bottom:7px; display:flex;
               justify-content:space-between; align-items:center; width:196px }
  .stop { font:11px system-ui,sans-serif; padding:2px 8px; border-radius:5px;
          background:#fff; cursor:pointer; border:1px solid var(--line) }
  .stop:hover { background:#f0f0ee }
  .wire-label { position:absolute; font-size:11px; color:var(--muted);
                background:#f7f7f5; padding:0 5px; z-index:2; cursor:help;
                transform:translate(-50%,-50%) }
  .teach { position:fixed; left:0; right:0; bottom:40px; background:#fff; height:104px;
           border-top:1px solid var(--line); padding:13px 20px; overflow:hidden }
  .teach .inner { max-width:1180px; margin:0 auto }
  .teach h3 { margin:0 0 3px; font-size:13px }
  .teach p { margin:0 0 5px; font-size:13px; color:#333; max-width:820px }
  .teach code { background:#f0f0ee; padding:1px 6px; border-radius:3px; font-size:12px }
  .teach .idle { color:var(--muted) }
  .bar { position:fixed; left:0; right:0; bottom:0; background:#1c1c1c; color:#fff;
         padding:8px 16px; display:flex; gap:11px; align-items:center; font-size:13px }
  .bar button { padding:3px 10px; border-radius:5px; background:#333; color:#fff;
                font:inherit; cursor:pointer; border:1px solid var(--bar-line) }
  .bar .proto { margin-left:auto; color:#bbb }
</style>

<header>
  <h1>Factory</h1>
  <span class="chip" data-teach="launcher">started by <b>the Launcher</b>
    <span id="launcher-addr"></span> — outside the factory</span>
</header>
<p class="sub">Every box is a running participant, and every arrow is a link between two of
   them. Point at anything to read what it is and which file to open.</p>

<div class="stage" id="stage">
  <svg class="wires" id="wires"></svg>
  <div id="layers"></div>
</div>

<div class="teach" id="teach"></div>

<div class="bar">
  <span>prototype scenes:</span>
  <button onclick="scene('reset')">two units</button>
  <button onclick="scene('starting')">still starting</button>
  <button onclick="scene('failed')">one failure</button>
  <button onclick="scene('four')">four units</button>
  <span class="proto">PROTOTYPE — the factory behind this page is a fake</span>
</div>

<script>
const TEACH = __TEACH__;
const SOURCES = __SOURCES__;
let frozen = false;

function box(key, id, title, node, wide) {
  const addr = node.address
    ? `<a href="http://${node.address}" target="_blank">${node.address}</a>` +
      `<span class="src" data-src="${node.source}">${node.source}</span>`
    : `<span class="none">${node.state === 'stopped' ? 'stopped' : 'no address yet'}</span>`;
  return `<div class="box ${node.state} ${wide ? 'wide' : ''}" id="${id}"
               data-teach="${key}">
            <h2><span class="dot"></span>${title}</h2>
            <div class="state">${node.state}${node.pid ? ' — pid ' + node.pid : ''}</div>
            <div class="addr">${addr}</div>
          </div>`;
}

function render(s) {
  const n = s.unit.length;
  const cols = `grid-template-columns:repeat(${n}, 196px); justify-content:center;
                column-gap:${n > 3 ? 26 : 96}px`;

  const plcs = s.unit.map(u => `
    <div>
      <div class="unit-head"><span>TransferUnit ${u.index}</span>
        <button class="stop" onclick="stopUnit(${u.index})">stop</button></div>
      ${box('plc', 'plc-' + u.index, 'PLC and panel', u.plc)}
    </div>`).join('');

  const mws = s.unit.map(u =>
    box('middleware', 'mw-' + u.index, 'middleware ' + u.index, u.middleware)).join('');

  document.getElementById('layers').innerHTML = `
    <div class="layer" style="${cols}">${plcs}</div>
    <div class="layer one">${box('broker', 'broker', 'MQTT broker', s.broker, true)}</div>
    <div class="layer" style="${cols}">${mws}</div>
    <div class="layer one">${box('graph', 'graph', 'knowledge graph', s.graph, true)}</div>
    <div class="layer one">
      ${box('controller', 'controller', 'control station', s.controller, true)}</div>`;

  document.getElementById('launcher-addr').innerHTML =
    `<a href="http://${s.launcher.address}">${s.launcher.address}</a>`;

  wires(s);
  bind();
}

function edge(id, side) {
  const el = document.getElementById(id);
  if (!el) return null;
  const s = document.getElementById('stage').getBoundingClientRect();
  const r = el.getBoundingClientRect();
  return { x: r.left - s.left + r.width / 2,
           y: (side === 'top' ? r.top : r.bottom) - s.top,
           left: r.left - s.left, right: r.right - s.left };
}

function wires(s) {
  const svg = document.getElementById('wires');
  const stage = document.getElementById('stage');
  svg.style.height = stage.scrollHeight + 'px';
  svg.setAttribute('viewBox', `0 0 ${stage.clientWidth} ${stage.scrollHeight}`);

  let paths = '', labels = '';
  function wire(d, key, text, lx, ly) {
    paths += `<path d="${d}" data-wire="${key}"></path>`;
    labels += `<div class="wire-label" data-teach="${key}"
                    style="left:${lx}px; top:${ly}px">${text}</div>`;
  }
  function straight(fromId, toId, key, text) {
    const a = edge(fromId, 'bottom'), b = edge(toId, 'top');
    if (!a || !b) return;
    const mid = (a.y + b.y) / 2;
    wire(`M ${a.x} ${a.y} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${b.y}`,
         key, text, (a.x + b.x) / 2, mid);
  }

  for (const u of s.unit) {
    straight('plc-' + u.index, 'broker', 'arrow-plc-broker', 'MQTT');
    straight('broker', 'mw-' + u.index, 'arrow-broker-mw', 'MQTT');
    straight('mw-' + u.index, 'graph', 'arrow-mw-graph', 'OGM');
  }
  straight('graph', 'controller', 'arrow-graph-ctrl', 'discovery');

  // The REST arrow jumps two layers, so it bows around the right edge of the stage.
  const ctrl = edge('controller', 'top');
  const first = edge('mw-' + s.unit[0].index, 'bottom');
  if (ctrl && first) {
    const bow = stage.clientWidth - 14;
    for (const u of s.unit) {
      const m = edge('mw-' + u.index, 'bottom');
      if (!m) continue;
      paths += `<path d="M ${ctrl.right} ${ctrl.y + 18} C ${bow} ${ctrl.y},
                         ${bow} ${m.y}, ${m.x} ${m.y}" data-wire="arrow-ctrl-mw"></path>`;
    }
    labels += `<div class="wire-label" data-teach="arrow-ctrl-mw"
                    style="left:${bow - 20}px; top:${(ctrl.y + first.y) / 2}px">REST</div>`;
  }

  svg.innerHTML = paths;
  document.querySelectorAll('.wire-label').forEach(n => n.remove());
  stage.insertAdjacentHTML('beforeend', labels);
}

function bind() {
  document.querySelectorAll('[data-teach]').forEach(el => {
    el.onmouseenter = () => teach(el.dataset.teach, el);
    el.onmouseleave = idle;
  });
  document.querySelectorAll('.src').forEach(el => {
    el.onmouseenter = ev => { ev.stopPropagation(); source(el.dataset.src); };
  });
}

function teach(key, el) {
  const t = TEACH[key];
  if (!t) return;
  frozen = true;
  el.classList.add('hot');
  document.querySelectorAll(`[data-wire="${key}"]`).forEach(p => p.classList.add('hot'));
  document.querySelectorAll(`[data-teach="${key}"]`).forEach(n => n.classList.add('hot'));
  document.getElementById('teach').innerHTML =
    `<div class="inner"><h3>${t.title}</h3><p>${t.what}</p>
     <p>Open <code>${t.file}</code>.</p></div>`;
}

function source(src) {
  frozen = true;
  document.getElementById('teach').innerHTML =
    `<div class="inner"><h3>Where this address came from</h3><p>${SOURCES[src]}</p></div>`;
}

function idle() {
  frozen = false;
  document.querySelectorAll('.hot').forEach(n => n.classList.remove('hot'));
  document.getElementById('teach').innerHTML =
    '<div class="inner"><p class="idle">Point at a box or an arrow.</p></div>';
}

async function stopUnit(i) {
  render(await (await fetch('/api/stop/' + i, {method:'POST'})).json());
}
async function scene(name) {
  render(await (await fetch('/api/prototype/' + name, {method:'POST'})).json());
}
async function poll() {
  if (frozen) return;
  render(await (await fetch('/api/state')).json());
}
idle();
poll();
setInterval(poll, 1000);
window.onresize = () => { frozen = false; poll(); };
</script>
"""


if __name__ == "__main__":
    print("Launcher index prototype on http://127.0.0.1:8812/")
    uvicorn.run(app, host="127.0.0.1", port=8812, log_level="warning")
