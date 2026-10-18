"use strict";
window.ResearchDesk=(()=>{
  let root,handlers,data={},project=null,active="overview",picked=new Set(),focus=null;
  const views={overview:"研究驾驶舱",library:"材料与阅读",ideas:"Idea 与实验",review:"决策复盘",settings:"项目与目标"};
  const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  function button(text,fn){const b=el("button",text);b.type="button";b.onclick=()=>Promise.resolve(fn()).catch(e=>notice(e.message));return b;}
  function areaOf(action){if(/project|profile/.test(action))return "settings";if(/idea|experiment/.test(action))return "ideas";if(/decision/.test(action))return "review";return "library";}
  function show(view){active=view;root.dataset.view=view;root.querySelectorAll("[data-desk-view]").forEach(b=>{b.classList.toggle("active",b.dataset.deskView===view);b.setAttribute("aria-selected",String(b.dataset.deskView===view));});}
  function reveal(target){tab("workspace");const area=target.closest("[data-desk-area]");if(area)show(area.dataset.deskArea);const details=target.closest("details");if(details)details.open=true;target.scrollIntoView({behavior:"smooth",block:"center"});}
  function jump(action,entry){const form=root.querySelector(`[data-workspace-action="${action}"]`);reveal(form);if(entry)handlers.edit(action,entry);else{form.reset();form.elements.id.value="";form.elements.revision.value="";}}
  function install(workspace,callbacks){
    root=workspace;handlers=callbacks;
    for(const child of root.children){const form=child.querySelector("[data-workspace-action]");child.dataset.deskArea=form?areaOf(form.dataset.workspaceAction):child.querySelector("#library-list")||child.id==="workspace-reader"?"library":child.querySelector("#idea-list,#experiment-list")?"ideas":child.querySelector("#decision-list")?"review":"overview";}
    const nav=el("div",undefined,"desk-tabs");nav.setAttribute("role","tablist");nav.setAttribute("aria-label","研究工作视图");
    for(const [key,title] of Object.entries(views)){const b=button(title,()=>show(key));b.dataset.deskView=key;b.setAttribute("role","tab");nav.append(b);}root.prepend(nav);
    const overview=el("div",undefined,"desk-overview");overview.id="desk-overview";overview.dataset.deskArea="overview";nav.after(overview);
    const context=root.querySelector("#workspace-project").closest(".panel"),summary=el("section",undefined,"panel desk-summary");summary.dataset.deskArea="overview";
    for(const child of [...context.children])if(child.tagName==="BUTTON"||child.id==="workspace-stats")summary.append(child);
    context.removeAttribute("data-desk-area");context.classList.add("desk-project-switcher");nav.after(context);context.after(overview);overview.after(summary);
    const toolbar=el("div",undefined,"desk-library-tools");toolbar.dataset.deskArea="library";
    const search=el("input");search.type="search";search.id="desk-search";search.placeholder="搜索标题、标签、会场、组织…";search.setAttribute("aria-label","筛选材料");search.oninput=filter;
    const select=el("select");select.id="desk-stage";select.setAttribute("aria-label","材料阅读状态");for(const [key,title] of Object.entries({all:"全部阅读状态",queued:"待读",reading:"在读",read:"已读",archived:"归档"}))select.add(new Option(title,key));select.onchange=filter;
    const count=el("span");count.id="desk-library-count";toolbar.append(search,select,count,button("导入新材料",()=>jump("workspace.import")));root.querySelector("#library-list").closest("details").before(toolbar);
    const comparison=el("section",undefined,"desk-comparison panel");comparison.id="desk-comparison";comparison.dataset.deskArea="library";toolbar.after(comparison);installSearch();show(active);
  }
  function installSearch(){
    const dialog=el("dialog",undefined,"desk-command");dialog.id="desk-command";dialog.setAttribute("aria-label","搜索当前研究项目");
    const heading=el("div",undefined,"desk-command-heading");heading.append(el("strong","搜索当前研究项目"),button("关闭",()=>dialog.close()));
    const input=el("input");input.type="search";input.placeholder="材料、笔记、Idea、实验…";input.setAttribute("aria-label","搜索研究记录");
    const list=el("div",undefined,"desk-command-results");dialog.append(heading,input,el("p","Ctrl / ⌘ K 打开 · ↓ 选择 · Enter 进入 · Esc 关闭","desk-muted"),list);root.append(dialog);
    function results(){list.replaceChildren();const query=input.value.trim().toLocaleLowerCase();
      const groups=[["材料",data.library||[],item=>item.document_id?handlers.openReader(item.id):jump("workspace.library.update",item)],
        ["笔记",[...(data.annotation||[]),...(data.knowledge||[]),...(data.personal_notes||[])],item=>{const material=data.library.find(x=>x.document_id===item.document_id);if(material)return handlers.openReader(material.id);notice("此笔记未关联可阅读材料。");}],
        ["Idea",data.idea||[],item=>jump("workspace.idea.save",item)],
        ["实验",data.experiment||[],item=>jump("workspace.experiment.save",item)]];
      let count=0;
      for(const [kind,records,open] of groups)for(const item of records){const title=item.title||item.text||item.question||item.id;const text=[title,item.hypothesis,item.answer,...(item.tags||[])].join(" ").toLocaleLowerCase();if(query&&!text.includes(query)||count>=20)continue;
        const b=button("",()=>{dialog.close();return open(item);});b.append(el("small",kind),el("span",title));list.append(b);count++;
        b.onkeydown=e=>{if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();const buttons=[...list.children],index=buttons.indexOf(b),next=index+(e.key==="ArrowDown"?1:-1);if(next<0)input.focus();else (buttons[next]||b).focus();}};
      }
      if(!count)list.append(el("p","没有匹配记录。可以切换项目，或先导入材料。","desk-muted"));
    }
    input.oninput=results;input.onkeydown=e=>{if(e.key==="ArrowDown"){e.preventDefault();list.querySelector("button")?.focus();}if(e.key==="Enter"){e.preventDefault();list.querySelector("button")?.click();}};
    const open=()=>{if(!dialog.open)dialog.showModal();input.value="";results();input.focus();};
    document.querySelector("header").append(button("搜索记录 · Ctrl K",open));
    document.addEventListener("keydown",event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="k"){event.preventDefault();open();}});
  }
  function actionCard(title,reason,label,fn){const card=el("article",undefined,"desk-action");card.append(el("h3",title),el("p",reason),button(label,fn));return card;}
  function render(state,projectId){
    data=state;project=projectId;picked=new Set([...picked].filter(id=>data.library.some(x=>x.id===id)));
    const overview=root.querySelector("#desk-overview");overview.replaceChildren();const current=data.projects.find(p=>p.id===project);
    const hero=el("section",undefined,"desk-hero");hero.append(el("span","RESEARCH IN MOTION","desk-eyebrow"),el("h2",current?.name||"让每一次阅读，都推进一个研究问题"),el("p",current?.question||"建立项目，连接材料、阅读洞察和可检验的假设。从你真实记录的工作出发。"));
    const controls=el("div",undefined,"desk-hero-actions");controls.append(button(current?"继续阅读":"创建第一个项目",()=>current?show("library"):jump("workspace.project.save")),button("查看研究脉络",()=>root.querySelector("#desk-graph").scrollIntoView({behavior:"smooth"})));hero.append(controls);overview.append(hero);
    const actions=el("section",undefined,"desk-actions");actions.append(el("h3","下一步，做一件有推进的事"));
    if(!current){actions.append(actionCard("先明确一个研究问题","所有建议都需要具体研究目标；此处不会自动创建示例数据。","创建项目",()=>jump("workspace.project.save")));}
    else{
      const unfinished=data.library.filter(x=>x.status==="reading"||x.status==="queued").sort((a,b)=>(a.status==="reading"?0:1)-(b.status==="reading"?0:1));
      const item=unfinished[0];if(item)actions.append(actionCard(item.status==="reading"?"续读："+item.title:"开始阅读："+item.title,"依据：材料当前状态为"+(item.status==="reading"?"在读":"待读")+"。",item.document_id?"打开阅读":"下载并导入",()=>item.document_id?handlers.openReader(item.id):handlers.act("workspace.library.acquire",{id:item.id})));
      const idea=data.idea.find(i=>i.invalid_source_ids?.length||!i.source_ids.length);
      if(idea)actions.append(actionCard("补齐假设的依据",idea.title+" 尚有缺失或失效来源，建议先核对笔记。","检查 Idea",()=>jump("workspace.idea.save",idea)));
      const exp=data.experiment.find(x=>x.status==="running"||x.status==="designed");
      if(exp)actions.append(actionCard("推进一次可检验的实验",exp.title+"；当前"+(exp.status==="running"?"进行中":"已设计")+"，实际结果"+(exp.actual_result?"已有记录":"尚未记录")+"。","查看实验",()=>jump("workspace.experiment.save",exp)));
      const today=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
      const due=data.decision.find(x=>x.review_date&&x.review_date<=today);
      if(due)actions.append(actionCard("回访一个过去的选择",due.question+"；计划回访日 "+due.review_date+"。","复盘决策",()=>jump("workspace.decision.save",due)));
      if(!item&&!idea&&!exp&&!due)actions.append(actionCard("把积累变成一个问题",data.annotation.length?"已有阅读批注，可以综合证据并提出待验证假设。":"从一篇论文或工程报告开始，留下你的第一条批注。",data.annotation.length?"综合阅读笔记":"添加材料",()=>data.annotation.length?handlers.act("workspace.synthesize",{project_id:project,days:Number(document.querySelector("#workspace-days").value)||7}):jump("workspace.import")));
      else if(data.annotation.length&&actions.children.length<4)actions.append(actionCard("连接已读内容的共同问题",`当前项目已保存 ${data.annotation.length} 条批注。可按所选时间窗综合笔记，检查共识、分歧与待验证假设。`,"综合阅读笔记",()=>handlers.act("workspace.synthesize",{project_id:project,days:Number(document.querySelector("#workspace-days").value)||7})));
    }
    overview.append(actions);renderGraph(overview);
    for(const card of root.querySelectorAll("#library-list [data-library-id]")){const id=card.dataset.libraryId;const b=button(picked.has(id)?"移出对比":"加入对比",()=>{if(picked.has(id))picked.delete(id);else if(picked.size<4)picked.add(id);else return notice("每次最多比较 4 份材料，请先移出一份。");b.textContent=picked.has(id)?"移出对比":"加入对比";renderComparison();});b.dataset.compare=id;card.append(b);}
    filter();renderComparison();
  }
  function filter(){const query=root.querySelector("#desk-search").value.trim().toLocaleLowerCase(),status=root.querySelector("#desk-stage").value;let count=0;
    for(const card of root.querySelectorAll("#library-list [data-library-id]")){const item=data.library.find(x=>x.id===card.dataset.libraryId);const match=(!query||[item.title,item.venue,item.organization,...item.tags].join(" ").toLocaleLowerCase().includes(query))&&(status==="all"||item.status===status);card.hidden=!match;if(match)count++;}
    root.querySelector("#desk-library-count").textContent=`${count} / ${(data.library||[]).length} 份材料`;
  }
  function notesFor(item){return [...data.annotation,...data.knowledge,...(data.personal_notes||[])].filter(n=>n.document_id===item.document_id);}
  function renderComparison(){const target=root.querySelector("#desk-comparison");target.replaceChildren(el("h3","材料对比 · 把差异放到同一张桌上"));
    if(!picked.size){target.append(el("p","在材料卡上点击「加入对比」，最多选 4 份。比较内容来自你的批注和已确认知识，不根据标题猜测结论。","desk-muted"));return;}
    const items=data.library.filter(x=>picked.has(x.id)),rows=[["维度",...items.map(x=>x.title)],["来源",...items.map(x=>x.source_url||"未记录")]];
    for(const [label,kinds] of [["方法 / 实践",["method","industry"]],["贡献 / 发现",["finding"]],["局限 / 疑问",["limitation","question"]],["阅读笔记",["note","highlight","term",undefined]]])rows.push([label,...items.map(x=>notesFor(x).filter(n=>kinds.includes(n.kind)).slice(0,5).map(n=>(n.text||n.notes||n.answer)+" ["+n.id+"]").join("\n\n")||"尚未记录")]);
    const wrap=el("div",undefined,"desk-table-scroll"),table=el("table");table.setAttribute("aria-label","材料证据对比");for(const [index,row] of rows.entries()){const tr=el("tr");for(const value of row)tr.append(el(index===0?"th":"td",value));table.append(tr);}wrap.append(table);target.append(wrap);
    target.append(button("导出对比 Markdown",()=>{const escape=s=>String(s).replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\|/g,"\\|").replace(/\r?\n/g,"<br>");const text="# 材料证据对比\n\n"+rows.map((r,i)=>"| "+r.map(escape).join(" | ")+" |"+(i===0?"\n| "+r.map(()=>"---").join(" | ")+" |":"")).join("\n");const url=URL.createObjectURL(new Blob([text],{type:"text/markdown;charset=utf-8"}));const a=el("a");a.href=url;a.download="research-comparison.md";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}),button("清空对比",()=>{picked.clear();root.querySelectorAll("[data-compare]").forEach(b=>b.textContent="加入对比");renderComparison();}));
  }
  function graphData(){const nodes=[],edges=[],groups=[data.library,[...data.annotation,...data.knowledge,...(data.personal_notes||[])],data.idea,data.experiment];
    groups.forEach((records,column)=>records.slice(0,15).forEach((item,row)=>nodes.push({id:item.id,item,column,row,title:item.title||item.text||item.question||item.hypothesis||item.id})));
    const ids=new Set(nodes.map(n=>n.id));for(const node of nodes){const item=node.item;if(node.column===1){for(const lib of data.library)if(lib.document_id&&lib.document_id===item.document_id&&(!item.project_id||lib.project_id===item.project_id))edges.push([lib.id,node.id]);}if(node.column===2)for(const id of item.source_ids)edges.push([id,node.id]);if(node.column===3)edges.push([item.idea_id,node.id]);}
    return {nodes,edges:edges.filter(([a,b])=>ids.has(a)&&ids.has(b)),total:groups.reduce((n,g)=>n+g.length,0)};
  }
  function renderGraph(overview){const box=el("section",undefined,"desk-graph panel");box.id="desk-graph";box.append(el("h3","你的研究脉络"),el("p","材料 → 阅读证据 → 待验证假设 → 实验。连线表示你保存的关联，不表示论文引用或自动验证。","desk-muted"));
    const graph=graphData(),wrap=el("div",undefined,"desk-graph-scroll"),ns="http://www.w3.org/2000/svg";
    const svg=document.createElementNS(ns,"svg");svg.setAttribute("viewBox",`0 0 1000 ${Math.max(150,(Math.max(0,...graph.nodes.map(n=>n.row))+1)*74+60)}`);svg.setAttribute("role","group");svg.setAttribute("aria-label","材料笔记 Idea 实验关联图");
    const make=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))n.setAttribute(key,value);if(text)n.textContent=text;return n;};
    const defs=make("defs",{}),marker=make("marker",{id:"desk-arrow",viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:6,markerHeight:6,orient:"auto"});marker.append(make("path",{d:"M 0 0 L 10 5 L 0 10 z",fill:"#7a9a88"}));defs.append(marker);svg.append(defs);
    ["材料","笔记与知识","Idea","实验"].forEach((label,i)=>svg.append(make("text",{x:i*250+20,y:25,class:"desk-column-label"},label)));
    const positions=new Map(graph.nodes.map(n=>[n.id,{x:n.column*250+16,y:46+n.row*74}]));
    for(const [a,b] of graph.edges){const p=positions.get(a),q=positions.get(b);const path=make("path",{d:`M ${p.x+214} ${p.y+26} C ${p.x+240} ${p.y+26},${q.x-26} ${q.y+26},${q.x-2} ${q.y+26}`,class:"desk-edge","marker-end":"url(#desk-arrow)"});path.dataset.from=a;path.dataset.to=b;svg.append(path);}
    const inspector=el("div",undefined,"desk-inspector");inspector.id="desk-inspector";inspector.append(el("p",graph.nodes.length?"选择任意节点，查看原始笔记、关联来源与下一步。":"这里还没有记录。从创建项目和导入材料开始，脉络会随着阅读自然生长。"));
    function inspect(node){focus=node.id;const related=new Set([node.id]);for(const [a,b] of graph.edges)if(a===focus||b===focus){related.add(a);related.add(b);}svg.querySelectorAll(".desk-graph-node").forEach(n=>n.classList.toggle("dimmed",!related.has(n.dataset.id)));svg.querySelectorAll(".desk-edge").forEach(e=>e.classList.toggle("selected",e.dataset.from===focus||e.dataset.to===focus));
      inspector.replaceChildren(el("h4",node.title),el("small",node.id),el("p",node.item.text||node.item.answer||node.item.hypothesis||node.item.actual_result||"已保存的材料记录"));
      if(node.item.invalid_source_ids?.length)inspector.append(el("p","失效来源："+node.item.invalid_source_ids.join(", "),"workspace-warning"));
      if(node.column===0)inspector.append(button("打开材料",()=>node.item.document_id?handlers.openReader(node.id):jump("workspace.library.update",node.item)));
      if(node.column===1){const lib=data.library.find(x=>x.document_id===node.item.document_id);if(lib)inspector.append(button("回到原文",()=>handlers.openReader(lib.id)));}
      if(node.column===2||node.column===3)inspector.append(button(node.column===2?"检查 Idea":"查看实验",()=>jump(node.column===2?"workspace.idea.save":"workspace.experiment.save",node.item)));
    }
    const meta={queued:"待读",reading:"在读",read:"已读",archived:"归档",draft:"假设草稿",needs_evidence:"待补充证据",ready:"准备验证",testing:"验证中",supported:"获得支持",rejected:"未获支持",designed:"已设计",running:"进行中",completed:"已完成",failed:"未完成",paused:"暂停",method:"方法批注",industry:"行业笔记",note:"阅读笔记",highlight:"重点",question:"疑问",finding:"发现",limitation:"局限",term:"术语",confirmed:"已确认知识"};
    for(const node of graph.nodes){const p=positions.get(node.id),g=make("g",{class:`desk-graph-node desk-kind-${node.column}`,tabindex:0,role:"button","aria-label":node.title});g.dataset.id=node.id;g.append(make("rect",{x:p.x,y:p.y,width:214,height:56,rx:10}),make("text",{x:p.x+12,y:p.y+24},Array.from(node.title).slice(0,16).join("")+(Array.from(node.title).length>16?"…":"")),make("text",{x:p.x+12,y:p.y+43,class:"desk-node-meta"},meta[node.item.status||node.item.kind]||"已保存记录"));g.onclick=()=>inspect(node);g.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();inspect(node);}};svg.append(g);}
    wrap.append(svg);box.append(wrap,el("small",`显示 ${graph.nodes.length} / ${graph.total} 条记录，每列最多 15 条；完整记录请切换相应工作视图。`),inspector);overview.append(box);
    if(focus){const node=graph.nodes.find(n=>n.id===focus);if(node)inspect(node);}
  }
  return {install,render,reveal,show,jump};
})();
