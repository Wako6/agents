"use strict";
// Aucune donnée n'est insérée comme HTML : tout passe par textContent, car titres et rapports viennent d'agents.
const VIEWS = [["projects","Projets"],["teams","Équipes"],["tasks","Tâches"],["pipeline","Pipeline"],["decisions","Décisions"],["security","Sécurité"]];
const STALE_S = 300;
const LABEL = {OPEN:["À lancer","idle"],IN_PROGRESS:["En cours","warn"],READY_FOR_VERIFICATION:["À vérifier","warn"],READY_FOR_REVIEW:["À relire","warn"],BLOCKED:["Bloquée","bad"],ESCALATED:["Escaladée","bad"],STALE:["Périmée","bad"],DONE:["Terminée","ok"],
  running:["En cours","warn"],done:["Livrée","ok"],failed:["Échec","bad"],aborted:["Arrêtée","bad"],interrupted:["Interrompue","bad"],
  OBSERVED_ALIVE:["Vivant, observé","warn"],OBSERVED_GONE:["Terminé, observé","ok"],
  PASS:["PASS","ok"],FAIL:["FAIL","bad"],INCONCLUSIVE:["Non concluant","bad"],APPROVE:["APPROVE","ok"],CHANGES_REQUESTED:["Modifications demandées","bad"],UNPARSEABLE:["Illisible","bad"],
  STOPPED:["Arrêt prouvé","ok"],UNRESOLVED:["Arrêt non résolu","bad"],
  OBSERVED:["Observé","ok"],DECLARED:["Déclaré","warn"],NOT_MEASURED:["Non mesuré","unk"],
  OK:["Lisible","ok"],PARTIAL:["Partielle","warn"],UNREADABLE:["Illisible","bad"],
  active:["En cours","warn"],blocked:["Bloqué","bad"],pending:["À venir","idle"]};
LABEL.IN_PROGRESS_STOP = ["Arrêt interrompu","bad"];
const $ = id => document.getElementById(id);
const el = (tag, cls, ...kids) => { const n = document.createElement(tag); if (cls) n.className = cls;
  for (const k of kids) if (k !== null && k !== undefined) n.append(k.nodeType ? k : String(k)); return n; };
let snap = null, runId = null, es = null, cut = false, lastSeen = null, lost = null;

function tag(st, ctx) {
  if (!st) return el("span","tag unk","Inconnu");
  const v = st.value || st;
  if (v === "UNKNOWN") return el("span","tag unk", "Inconnu" + (st.raw ? " : " + st.raw : ""));
  if (ctx === "phase" && v === "done") return el("span","tag ok","Fait");
  const key = ctx === "stop" && v === "IN_PROGRESS" ? "IN_PROGRESS_STOP" : v;
  const [txt, cls] = LABEL[key] || ["Inconnu : " + v, "unk"];
  return el("span","tag "+cls, txt);
}
const fmt = ts => { if (!ts) return "—"; const d = new Date(ts); return isNaN(d) ? "inconnu" : d.toLocaleString("fr-FR",{dateStyle:"short",timeStyle:"medium"}); };
const hm = ts => { const d = new Date(ts); return isNaN(d) ? "inconnu" : d.toLocaleTimeString("fr-FR"); };
const age = ts => { const d = new Date(ts); if (!ts || isNaN(d)) return null; return Math.max(0,(Date.now()-d)/1000); };
const ago = ts => { const a = age(ts); if (a === null) return "inconnue"; return a < 90 ? Math.round(a)+" s" : a < 5400 ? Math.round(a/60)+" min" : Math.round(a/3600)+" h"; };
function allRuns(){ return snap ? snap.projects.flatMap(p => p.runs.map(r => ({p,r}))) : []; }
function cur(){ return allRuns().find(x => x.r.id === runId) || allRuns()[0] || null; }
function table(heads, rows){ const t = el("table"); const h = el("tr"); heads.forEach(x=>h.append(el("th",null,x))); t.append(el("thead",null,h));
  const b = el("tbody"); rows.forEach(r=>{const tr=el("tr"); r.forEach(c=>tr.append(el("td",null,c))); b.append(tr);}); t.append(b); return el("div","scroll",t); }
const kv = pairs => { const d = el("dl","kv"); pairs.forEach(([k,v])=>{d.append(el("dt",null,k),el("dd",null,v??"—"));}); return d; };
const freshness = r => { const a = age(r.observed_at); return a === null || a > STALE_S; };

const render = {
  projects(){ const g = el("div","grid");
    snap.projects.forEach(p => { const runs = p.runs.map(r => { const c = r.tasks||[]; const open = c.filter(t=>t.status&&!["DONE"].includes(t.status.value)).length;
        const stop = r.security&&r.security.stop&&r.security.stop.state;
        return el("p",null, el("a",null,r.id), " ", stop?tag(stop,"stop"):null, " ", el("span","muted", open+" tâche(s) ouverte(s), observé il y a "+ago(r.observed_at))); });
      runs.forEach(n=>{const a=n.querySelector("a"); const id=a.textContent; a.href="#tasks"; a.addEventListener("click",()=>{runId=id;$("run").value=id;});});
      g.append(el("section","card", el("h3",null,p.name), kv([["Registre",p.backend],["Mode",p.mode],["Source",tag(p.source)],["Profil",(p.profile||"aucun")+(p.profile_active?"":" (non activé)")]]), ...runs)); });
    return [el("p","sub","Vue d'ensemble. Le cockpit lit des fichiers ; il n'interroge aucun agent et ne lance rien."),g]; },
  teams(r){ const g = el("div","grid"); (r.teams||[]).forEach(t => g.append(el("section","card",el("h3",null,t.name),kv([["CLI",t.adapter],["Rôle",t.role],["Tâche",t.task],["Cgroup",t.cgroup],["Processus",t.processes==null?"inconnu":t.processes],["Observé",fmt(t.observed_at)+" (il y a "+ago(t.observed_at)+")"]]))));
    return [el("p","sub","Agents de ce run. Le nombre de processus est une observation datée, pas un état garanti."), g]; },
  tasks(r){ const rows = (r.tasks||[]).map(t => { const a = (t.attempts||[]).at(-1)||{};
      return [el("div",null,el("div",null,t.title),el("div","muted mono",t.wi+" · "+t.key)), tag(t.status), t.team, el("div",null,(a.n?"#"+a.n+" ":""),tag(a.result),el("div","muted",t.budget||"")), a.liveness?tag(a.liveness):tag(null), t.verify?tag(t.verify.verdict):"—", t.review?el("div",null,tag(t.review.verdict),t.review.uncovered&&t.review.uncovered.length?el("div","muted",t.review.uncovered.length+" point(s) de contrôle absent(s)"):null):"—", el("div","mono",t.commit||"—"), t.blocker||"—"]; });
    const ev = el("ul","ev"); (r.events||[]).slice(-12).reverse().forEach(e=>ev.append(el("li",null,el("time",null,hm(e.ts)),el("span",null,e.severity&&e.severity.value==="critical"?el("span","tag bad","Critique"):e.severity&&e.severity.value==="warning"?el("span","tag warn","Attention"):null," ",e.text||e.kind))));
    return [table(["Tâche","État","Équipe","Tentative","Processus","Docker","Revue","Commit","Blocage"],rows), el("h2",null,"Derniers événements"), el("div","scroll",ev)]; },
  pipeline(r){ const ol = el("ol","pipe"); (r.pipeline||[]).forEach(s=>{ const t = tag(s.state,"phase"); ol.append(el("li",t.className.replace("tag ",""),el("b",null,s.label),t,el("small",null,s.detail||""))); });
    return [el("p","sub","Étape dérivée des fichiers du run. Une étape non établie reste « Inconnu », jamais réussie par défaut."),ol]; },
  decisions(r){ return [el("p","sub","Décisions humaines et validations enregistrées. Un acquittement n'est pas une preuve technique."), table(["Date","Type","Par","Contenu"],(r.decisions||[]).map(d=>[fmt(d.ts),d.kind,d.by||"—",d.text]))]; },
  security(r){ const s = r.security||{}; const st = s.stop||{};
    const items = table(["Contrôle","Valeur","Preuve","Note"],(s.items||[]).map(i=>[i.label,i.value,tag(i.proof),i.note||"—"]));
    const nm = (s.items||[]).filter(i=>!i.proof||i.proof.value!=="OBSERVED").length;
    return [el("section","card",el("h3",null,"Arrêt critique"),kv([["Verdict technique",st.state?tag(st.state,"stop"):el("span","muted","aucun arrêt enregistré")],["Motif",st.reason],["Acquittement",st.ack_by?st.ack_by+" (ne prouve rien, ne débloque rien)":"—"]])),
      el("h2",null,"Contrôles de ce run"), el("p","sub",nm+" point(s) sans preuve observée. Le cockpit n'affiche aucun verdict global du type « sécurisé »."), items]; }
};

function banner(c){ const b = $("banner"); b.className = ""; b.textContent = ""; const msgs = [];
  if (lost) msgs.push(["Flux coupé depuis "+hm(lost)+". Les données affichées datent de "+(lastSeen?hm(lastSeen):"inconnu")+". Reconnexion en cours.","bad"]);
  if (c) { const r = c.r; const v = r.source&&r.source.value;
    if (v==="UNREADABLE") msgs.push(["Source illisible : "+(r.source_note||"")+" États affichés comme inconnus.","bad"]);
    else if (v==="PARTIAL") msgs.push(["Source partielle : "+(r.source_note||""),"warn"]);
    if (r.security&&r.security.stop&&r.security.stop.state&&["UNRESOLVED","IN_PROGRESS"].includes(r.security.stop.state.value)) msgs.push(["Arrêt critique non prouvé : aucune équipe ne repart, rien ne s'intègre. Vérifiez les processus dans la vue Sécurité.","bad"]);
    if (freshness(r) && !lost) msgs.push(["Aucune observation depuis "+ago(r.observed_at)+" : cet état peut être dépassé.","warn"]); }
  if (msgs.length) { b.textContent = msgs.map(m=>m[0]).join(" "); if (msgs.some(m=>m[1]==="bad")) b.className = "bad"; } }

function draw(){ const hash = (location.hash||"#projects").slice(1); const view = VIEWS.some(v=>v[0]===hash)?hash:"projects";
  $("tabs").replaceChildren(...VIEWS.map(([k,l])=>{const a=el("a",null,l);a.href="#"+k;if(k===view)a.setAttribute("aria-current","page");return a;}));
  if (!snap) return; const c = cur(); banner(c);
  const sel = $("run"); const opts = allRuns().map(x=>x.r.id); if ([...sel.options].map(o=>o.value).join()!==opts.join()) sel.replaceChildren(...allRuns().map(x=>{const o=el("option",null,x.p.name+" · "+x.r.id);o.value=x.r.id;return o;}));
  if (c) { runId=c.r.id; sel.value=runId; }
  const head = view!=="projects"&&c ? [el("h2","runtitle",c.r.title||c.r.id)] : [];
  $("view").replaceChildren(...head,...(view==="projects"?render.projects():c?render[view](c.r):[el("p","muted","Aucun run.")])); }

function status(on,text){ $("live-dot").className="dot "+(on?"on":"off"); $("live-text").textContent=text; }
async function load(){ const res = await fetch("/api/v1/snapshot",{cache:"no-store"}); if(!res.ok) throw new Error(res.status); snap = await res.json(); lastSeen = new Date().toISOString(); draw(); }
function connect(){ if (es) es.close(); es = new EventSource("/api/v1/stream");
  es.addEventListener("hello", async e => { const h = JSON.parse(e.data); lost=null; status(true,"En direct"); if (!snap||h.resync||snap.instance!==h.instance||snap.seq!==h.seq) { try{ await load(); }catch{ status(false,"Instantané indisponible"); } } else draw(); });
  es.addEventListener("update", async () => { try{ await load(); }catch{ status(false,"Instantané indisponible"); } });
  es.onerror = () => { if(!lost) lost=new Date().toISOString(); status(false,"Hors ligne, reconnexion"); draw(); }; }
$("run").addEventListener("change",e=>{runId=e.target.value;draw();});
$("cut").addEventListener("click",()=>{ cut=!cut; $("cut").textContent=cut?"Rétablir le flux":"Simuler une coupure"; if(cut){es.close();lost=new Date().toISOString();status(false,"Hors ligne (simulé)");draw();} else {connect();} });
addEventListener("hashchange",draw);
setInterval(()=>{ if(snap&&!$("view").contains(document.activeElement)) draw(); },15000);
draw(); connect();
