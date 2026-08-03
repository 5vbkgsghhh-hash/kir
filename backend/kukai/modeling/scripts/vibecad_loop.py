#!/usr/bin/env python3
"""vibecad_loop.py — autonomous VibeCADding loop on the live model.

intent -> ground -> [DeepSeek writes Revit C#] -> exec (compile=lint) -> screenshot
(aimed at new geometry) -> [vision model critiques shape vs intent] -> fix -> iterate.

Two feedback channels, exactly like vibecoding:
  * TEXT  — compile/exec errors fed straight back to the codegen model;
  * VISION — a rendered screenshot fed to a vision model that critiques the FORM.

Standalone: litellm for the two LLMs, op_revit.py for the live exec+screenshot channel.
SAFETY: hard device allowlist (only the operator-authorized doc).
"""
from __future__ import annotations
import argparse, base64, json, os, re, subprocess, sys

VPY = "/opt/kukai-rebuild1/backend/venv/bin/python"
OP  = "/opt/kukai-rebuild1/scripts/op_revit.py"
AUTHORIZED = {"a6d7d14340bc599817ae7e6896182ca0"}          # Музе only — never another user's model
CODEGEN_MODEL = os.environ.get("KUKAI_LLM_MODEL", "openrouter/deepseek/deepseek-v4-flash")
VISION_MODEL  = os.environ.get("KUKAI_VIBECAD_VISION_MODEL", "openrouter/google/gemini-2.5-flash")
API_KEY  = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("KUKAI_LLM_API_KEY")
PROVIDER_PIN = {"provider": {"order": ["DeepInfra", "Novita", "AtlasCloud"], "allow_fallbacks": True}}

import litellm

# ---- live channel (op_revit subprocess) ----
def _run(args, timeout=200):
    p = subprocess.run([VPY, OP, *args], capture_output=True, text=True, timeout=timeout)
    try: return json.loads(p.stdout)
    except Exception: return {"status": "ERR", "raw": p.stdout[-400:] + p.stderr[-400:]}

def op_exec(device, code, timeout_ms=60000):
    r = _run(["exec", device, "--timeout-ms", str(timeout_ms), "--code", code], timeout=timeout_ms/1000 + 40)
    if r.get("status") != 200: return {"error": True, "message": json.dumps(r)[:300]}
    return (r.get("body") or {}).get("result")

def op_shot(device, out):
    r = _run(["screenshot", device, "--filename", os.path.basename(out), "--out", out], timeout=90)
    res = (r.get("body") or {}).get("result") if isinstance(r, dict) else None
    return out if (res and res.get("image_base64")) else None

# ---- LLM hops ----
def _content(resp):
    try: return (resp.choices[0].message.content or "").strip()
    except Exception: return ""

def _strip_code(t):
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.DOTALL|re.I)
    m = re.search(r"```(?:csharp|cs|c#)?\s*\n?(.*?)```", t, re.DOTALL)
    t = (m.group(1) if m else t).strip()
    # The backend wraps our code into Kukai.UserCode.Execute(...). If the model ALSO
    # emitted its own Execute(...) method (double-wrap → CS0111), extract just its body.
    em = re.search(r"Execute\s*\([^)]*\)\s*\{", t)
    if em:
        i = em.end() - 1; depth = 0
        for j in range(i, len(t)):
            if t[j] == "{": depth += 1
            elif t[j] == "}":
                depth -= 1
                if depth == 0:
                    return t[i+1:j].strip()
    # otherwise drop leading using-directives (not `using (var…)`)
    out = [ln for ln in t.split("\n")
           if not (ln.strip().startswith("using ") and ln.strip().endswith(";") and "(" not in ln)]
    return "\n".join(out).strip()

def codegen(intent, ground_ctx, history):
    sys_p = (
        "You are a Revit BIM modeler doing VibeCADding. Your output is INSERTED verbatim as the BODY of\n"
        "  public static object Execute(Document doc, UIDocument uidoc) { <YOUR CODE HERE> }\n"
        "which the host already provides. THEREFORE output ONLY statements (and C# LOCAL functions if needed).\n"
        "ABSOLUTELY NO `using` directives, NO `namespace`, NO `class`, NO `Execute(...)` method, NO separate\n"
        "method definitions — those cause a double-wrap compile error. All these usings are ALREADY in scope:\n"
        "System, System.Linq, System.Collections.Generic, System.Text, Autodesk.Revit.DB, .DB.Architecture,\n"
        ".DB.Structure, .DB.Mechanical, .DB.Electrical, .DB.Plumbing, Autodesk.Revit.UI.\n"
        "Build the requested geometry ADDITIVELY and END by returning a Dictionary<string,object> with\n"
        "\"ids\" = List<object> of created element ids (each <el>.Id.ToString()) and a short \"note\".\n"
        "Coords in mm via UnitUtils.ConvertToInternalUnits(x, UnitTypeId.Millimeters). Free-form mass =\n"
        "DirectShape (GeometryCreationUtilities.CreateExtrusionGeometry + DirectShape.CreateElement + SetShape);\n"
        "slabs = Floor.Create; walls = Wall.Create; columns = doc.Create.NewFamilyInstance. One Transaction\n"
        "around all writes. NEVER System.IO/Net. No markdown, no prose — C# statements only.\n\nLIVE MODEL CONTEXT:\n" + ground_ctx
    )
    msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": f"INTENT: {intent}"}]
    for h in history:
        msgs.append({"role": "assistant", "content": "```csharp\n" + h["code"] + "\n```"})
        msgs.append({"role": "user", "content": h["feedback"]})
    kw = {"model": CODEGEN_MODEL, "messages": msgs, "temperature": 0.4, "max_tokens": 8000, "timeout": 120}
    if API_KEY: kw["api_key"] = API_KEY
    if str(CODEGEN_MODEL).startswith("openrouter/"): kw["extra_body"] = PROVIDER_PIN
    return _strip_code(_content(litellm.completion(**kw)))

def critique(intent, png_path):
    b64 = base64.b64encode(open(png_path, "rb").read()).decode()
    sys_p = ("You are an architecture critic. Compare the rendered Revit model (image) to the user's INTENT. "
             "Reply ONLY JSON: {\"done\": bool, \"issues\": [\"...\"], \"guidance\": \"one concrete next instruction\"}. "
             "done=true only if the form clearly satisfies the intent.")
    msgs = [{"role": "system", "content": sys_p},
            {"role": "user", "content": [
                {"type": "text", "text": f"INTENT: {intent}\nDoes the model match? What to fix next?"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]
    kw = {"model": VISION_MODEL, "messages": msgs, "temperature": 0.2, "max_tokens": 700, "timeout": 90}
    if API_KEY: kw["api_key"] = API_KEY
    txt = _content(litellm.completion(**kw))
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    try: return json.loads(m.group(0)) if m else {"done": False, "issues": ["unparseable critique"], "guidance": txt[:200]}
    except Exception: return {"done": False, "issues": ["unparseable critique"], "guidance": txt[:200]}

# ---- aim at new geometry (section box on union bbox of ids) + shoot ----
def aim_shoot(device, ids, out):
    idcsv = ",".join(str(int(i)) for i in ids if str(i).lstrip("-").isdigit())
    cs = ("var V=doc.ActiveView as View3D; if(V==null) return new Dictionary<string,object>{{\"error\",true}};\n"
          f"var ids=new long[]{{{idcsv}}}; XYZ mn=null,mx=null;\n"
          "foreach(var idv in ids){ var e=doc.GetElement(new ElementId(idv)); if(e==null) continue; var b=e.get_BoundingBox(null); if(b==null) continue;\n"
          " if(mn==null){mn=b.Min;mx=b.Max;} else {mn=new XYZ(Math.Min(mn.X,b.Min.X),Math.Min(mn.Y,b.Min.Y),Math.Min(mn.Z,b.Min.Z)); mx=new XYZ(Math.Max(mx.X,b.Max.X),Math.Max(mx.Y,b.Max.Y),Math.Max(mx.Z,b.Max.Z));} }\n"
          "if(mn==null) return new Dictionary<string,object>{{\"error\",true},{\"message\",\"no bbox\"}};\n"
          "double p=6000.0/304.8; var mi=new XYZ(mn.X-p,mn.Y-p,mn.Z-p); var ma=new XYZ(mx.X+p,mx.Y+p,mx.Z+p); var c=(mi+ma)*0.5;\n"
          "var fwd=new XYZ(0.55,0.78,-0.30).Normalize(); var ur=(Math.Abs(fwd.Z)>0.9)?XYZ.BasisY:XYZ.BasisZ; var up=(ur-fwd*(ur.DotProduct(fwd))).Normalize(); var eye=c-fwd*(1000.0/304.8);\n"
          "using(var t=new Transaction(doc,\"vibecad frame\")){t.Start(); var sb=new BoundingBoxXYZ(); sb.Min=mi; sb.Max=ma; V.SetSectionBox(sb); V.SetOrientation(new ViewOrientation3D(eye,up,fwd)); t.Commit();}\n"
          "try{foreach(UIView uv in uidoc.GetOpenUIViews()) if(uv.ViewId==V.Id){uv.ZoomToFit();break;}}catch{}\n"
          "return new Dictionary<string,object>{{\"ok\",true}};")
    op_exec(device, cs)
    return op_shot(device, out)

# ---- the loop ----
def loop(device, intent, max_iters, outdir):
    assert device in AUTHORIZED, f"device {device} not authorized"
    os.makedirs(outdir, exist_ok=True)
    gctx = json.dumps(op_exec(device, GROUND_CS), ensure_ascii=False)[:1500]
    print("GROUND:", gctx[:300])
    history = []
    for it in range(1, max_iters + 1):
        print(f"\n===== ITER {it} =====")
        code = codegen(intent, gctx, history)
        print("CODE (head):", code[:160].replace("\n", " "))
        if re.search(r"\.\s*Delete\s*\(", code):           # SAFETY: additive only, never delete the user's model
            history.append({"code": code, "feedback": "FORBIDDEN: your code called Delete. Build ADDITIVELY only — never delete elements."}); print("BLOCKED: deletion attempt"); continue
        res = op_exec(device, code) or {}
        if not isinstance(res, dict) or res.get("error"):
            fb = f"COMPILE/EXEC ERROR: {json.dumps(res)[:400]}. Fix the C# and return ids."
            print("EXEC ERROR ->", fb[:160]); history.append({"code": code, "feedback": fb}); continue
        ids = res.get("ids") or []
        print("EXEC ok:", res.get("note"), "| ids:", len(ids))
        if not ids:
            history.append({"code": code, "feedback": "No element ids returned — nothing built. Build the geometry and return ids."}); continue
        png = aim_shoot(device, ids, os.path.join(outdir, f"iter{it}.png"))
        if not png:
            print("screenshot failed — continuing on text only"); history.append({"code": code, "feedback": "Screenshot failed; assume not done, refine and return ids."}); continue
        verdict = critique(intent, png)
        print("CRITIQUE:", json.dumps(verdict, ensure_ascii=False)[:300], "| img:", png)
        if verdict.get("done"):
            print(f"\n✅ DONE in {it} iters. Final image: {png}"); return {"done": True, "iters": it, "image": png}
        fb = "Not done. Issues: " + "; ".join(verdict.get("issues", [])) + ". Next: " + str(verdict.get("guidance", ""))
        history.append({"code": code, "feedback": fb})
    print("\n⏹ budget exhausted"); return {"done": False, "iters": max_iters}

GROUND_CS = ("var lv=new FilteredElementCollector(doc).OfClass(typeof(Level)).Cast<Level>().Take(8).Select(l=>l.Name+\"@\"+Math.Round(l.Elevation*304.8)).ToList();\n"
             "var gr=new FilteredElementCollector(doc).OfClass(typeof(Grid)).GetElementCount();\n"
             "var fams=new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>().Where(s=>s.Category!=null&&s.Category.Id.IntegerValue==(int)BuiltInCategory.OST_StructuralColumns).Take(4).Select(s=>s.Family.Name+\":\"+s.Name).ToList();\n"
             "return new Dictionary<string,object>{{\"levels\",lv},{\"grid_count\",gr},{\"column_families\",fams}};")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("intent")
    ap.add_argument("--device", default="a6d7d14340bc599817ae7e6896182ca0")
    ap.add_argument("--iters", type=int, default=4)
    ap.add_argument("--outdir", default="/tmp/vibecad")
    a = ap.parse_args()
    if not API_KEY: sys.exit("no LLM API key (source prod .env)")
    print(json.dumps(loop(a.device, a.intent, a.iters, a.outdir), ensure_ascii=False))

if __name__ == "__main__":
    main()
