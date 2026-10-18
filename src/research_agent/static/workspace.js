"use strict";
window.PersonalWorkspace=(()=>{
  let state={},project=localStorage.getItem("research-project"),readerId=null,sequence=0;
  const types={paper:"科研论文",industry:"行业材料"},stages={queued:"待读",reading:"在读",read:"已读",archived:"归档"};
  const annotationKinds={note:"阅读笔记",highlight:"重点",question:"疑问",term:"术语",method:"方法",finding:"贡献/发现",limitation:"局限",industry:"行业实践"};
  const ideaStages={draft:"草稿",needs_evidence:"补充证据",ready:"准备验证",testing:"验证中",supported:"获得支持",rejected:"未获支持",paused:"暂缓"};
  const experimentStages={designed:"已设计",running:"进行中",completed:"已完成",failed:"未完成/失败",paused:"暂停"};
  const metricLabels={materials_added:"新增材料",reading_completions:"标记已读",self_reported_minutes:"自报阅读分钟",recorded_reading_days:"记录阅读天数",annotations:"批注",knowledge_cards:"知识卡片",ideas_created:"新增 Idea",experiments_completed:"完成实验"};
  function button(title,fn){const b=node("button",title);b.type="button";b.onclick=()=>Promise.resolve(fn()).catch(e=>notice(e.message));return b;}
  async function act(action,params){const task=await api("/tasks",{action,params});await watch(task.task_id);return task;}
  function selected(){if(!project)throw new Error("请先创建或选择研究项目。");return project;}
  function uploadControl(form){
    const label=node("label","上传 PDF、TXT 或 Markdown（最多 50 MB）"),input=node("input");input.type="file";input.accept=".pdf,.txt,.md";label.append(input);
    input.onchange=async()=>{const file=input.files[0];if(!file)return;input.disabled=true;notice("");try{
      if(file.size>50000000)throw new Error("文件超过 50 MB，请拆分材料。");
      const response=await fetch("/workspace/uploads?filename="+encodeURIComponent(file.name),{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});
      const data=await response.json();if(!response.ok)throw new Error(data.detail||"上传失败");
      form.elements.source.value=data.source;if(!form.elements.title.value)form.elements.title.value=file.name;
      notice("文件上传成功。确认标题和类型后，点击保存导入。");
    }catch(error){notice(error.message);}finally{input.disabled=false;}};
    form.insertBefore(label,form.querySelector("button.primary"));
  }
  function section(title,open=false){const d=node("details",undefined,"workspace-section");d.open=open;d.append(node("summary",title));return d;}
  function field(form,title,name,type="text",choices=null){
    const label=node("label",title),input=node(choices?"select":type==="textarea"?"textarea":"input");input.name=name;
    if(choices){for(const [value,text] of Object.entries(choices))input.add(new Option(text,value));}
    else if(type!=="textarea")input.type=type;
    if(type==="textarea")input.rows=3;
    if(type==="hidden"){input.type="hidden";form.append(input);return input;}
    label.append(input);form.append(label);return input;
  }
  function form(action,title,fields,needsProject=true){
    const f=node("form");f.dataset.workspaceAction=action;f.append(node("h3",title));
    field(f,"","id","hidden");field(f,"","revision","hidden");
    for(const row of fields)field(f,...row);
    const submit=node("button","保存","primary");submit.type="submit";f.append(submit);
    f.onsubmit=async event=>{event.preventDefault();notice("");submit.disabled=true;try{
      const params={};
      for(const input of f.elements){if(!input.name)continue;
        if(input.multiple){params[input.name]=[...input.selectedOptions].map(o=>o.value);continue;}
        if(input.type==="checkbox"){params[input.name]=input.checked;continue;}
        if(!input.value.trim())continue;
        params[input.name]=["keywords","venues","tags"].includes(input.name)?input.value.split(/[,，]/).map(t=>t.trim()).filter(Boolean):input.name==="revision"||input.type==="number"?Number(input.value):input.value.trim();
      }
      if(needsProject)params.project_id=selected();
      if(action==="workspace.import"&&!params.source&&params.text)params.source="workspace-text";
      if(action==="workspace.annotation.save"){
        const item=state.library?.find(i=>i.id===readerId);if(!item?.document_id)throw new Error("请先在材料库中打开一篇已导入的文章。");params.document_id=item.document_id;
      }
      await act(action,params);
    }catch(error){notice(error.message);}finally{submit.disabled=false;}};
    return f;
  }
  function edit(action,entry){
    const f=document.querySelector(`[data-workspace-action="${action}"]`);
    ResearchDesk.reveal(f);
    for(const input of f.elements){if(!input.name)continue;const value=entry[input.name];
      if(input.multiple){for(const option of input.options)option.selected=(value||[]).includes(option.value);}
      else input.value=Array.isArray(value)?value.join(", "):value??"";
    }
    if(f.closest("details"))f.closest("details").open=true;f.scrollIntoView({behavior:"smooth",block:"center"});
  }
  function fillOptions(name,records,title,includeEmpty=true){
    const input=document.querySelector(`[data-workspace-action] [name="${name}"]`);if(!input)return;
    const previous=[...input.selectedOptions].map(o=>o.value);input.replaceChildren();
    if(includeEmpty)input.add(new Option("请选择",""));
    for(const row of records)input.add(new Option(title(row),row.id));
    for(const option of input.options)option.selected=previous.includes(option.value);
  }
  function statsView(target,stats){
    target.replaceChildren();const grid=node("div",undefined,"workspace-metrics");
    for(const [key,title] of Object.entries(metricLabels)){const box=node("div",undefined,"workspace-metric");box.append(node("strong",String(stats.metrics[key])),node("small",title));grid.append(box);}
    target.append(grid,node("p",`${stats.period.start.slice(0,10)} 至 ${stats.period.end.slice(0,10)} · ${stats.period.timezone}`));
    for(const warning of stats.warnings)target.append(node("p",warning,"workspace-muted"));
  }
  async function load(){
    if(!$("workspace-project"))return;const token=++sequence;
    const days=Number($("workspace-days").value)||7;
    let data=await api(`/workspace/state?days=${days}${project?"&project_id="+encodeURIComponent(project):""}`);
    if(token!==sequence)return;
    if(project===null&&data.projects.length){project=data.projects[0].id;localStorage.setItem("research-project",project);return load();}
    if(project&&!data.projects.some(p=>p.id===project)){project="";localStorage.setItem("research-project","");return load();}
    state=data;
    const select=$("workspace-project");select.replaceChildren(new Option("全部项目（仅统计）",""));for(const p of data.projects)select.add(new Option(p.name,p.id));select.value=project||"";
    statsView($("workspace-stats"),data.stats);
    const current=data.projects.find(p=>p.id===project);$("workspace-question").textContent=current?`${current.question||"尚未填写研究问题"} · 下一步：${current.next_step||"待填写"}`:"先创建研究项目，将论文与行业材料归入同一研究问题。";
    $("library-list").replaceChildren();
    for(const item of data.library){
      const card=record(item.title,`${types[item.kind]} · ${stages[item.status]} · ${item.venue||"会场未核对"} · ${item.year||"年份未知"}\n${item.tags.join(" / ")}`,item.id);card.dataset.libraryId=item.id;
      if(item.source_url)card.append(link(item.source_url,"原始来源 ↗"));
      if(item.document_id)card.append(button("打开阅读与批注",()=>openReader(item.id)));
      else if(item.paper_id)card.append(button("分类下载并导入阅读",()=>act("workspace.library.acquire",{id:item.id})));
      if(item.pdf_path)card.append(link(`/workspace/library/${item.id}/pdf?download=true`,"下载归档 PDF"));
      card.append(button("整理材料",()=>{
        const f=document.querySelector('[data-workspace-action="workspace.library.update"]');edit("workspace.library.update",item);f.closest("details").open=true;
      }));
      if(item.status!=="read")card.append(button("标记已读",()=>act("workspace.library.update",{id:item.id,revision:item.revision,status:"read",tags:item.tags,venue:item.venue,organization:item.organization,source_status:item.source_status})));
      if(item.paper_id){card.append(button("扩展引用",()=>submitPaper("papers.related",{seed:item.paper_id,limit:20,similar_limit:5})),button("构建相似图",()=>submitPaper("papers.map",{seed:item.paper_id})));}
      $("library-list").append(card);
    }
    if(!data.library.length)$("library-list").append(node("p","材料库为空。从论文搜索结果加入材料，或导入行业文章。"));
    const notes=[...data.annotation,...data.knowledge,...(data.personal_notes||[])];
    fillOptions("source_ids",notes,n=>(n.text||n.question||n.id).slice(0,70),false);
    fillOptions("evidence_ids",notes,n=>(n.text||n.question||n.id).slice(0,70),false);
    fillOptions("idea_id",data.idea,i=>i.title);
    $("idea-list").replaceChildren(...data.idea.map(idea=>{
      const card=record(idea.title,`${idea.hypothesis}\n${ideaStages[idea.status]} · 新颖性${idea.novelty_status==="unchecked"?"待核验":"本人已复核"}\n证据：${idea.source_ids.join(", ")||"待补充"}\n下一步：${idea.next_step}`,idea.id);
      if(idea.invalid_source_ids.length)card.append(node("p","部分来源已失效，请补充证据。","workspace-warning"));
      card.append(button("编辑 Idea",()=>edit("workspace.idea.save",idea)),button("设计验证实验",()=>{const f=document.querySelector('[data-workspace-action="workspace.experiment.save"]');f.reset();f.elements.idea_id.value=idea.id;f.elements.title.value=idea.title+" · 验证";if(f.closest("details"))f.closest("details").open=true;f.scrollIntoView({behavior:"smooth"});}));return card;
    }));
    $("experiment-list").replaceChildren(...data.experiment.map(exp=>{
      const card=record(exp.title,`${experimentStages[exp.status]}\n基线：${exp.baseline}\n数据：${exp.dataset}\n指标：${exp.metrics}\n预期：${exp.expected_result||"未填写"}\n实际：${exp.actual_result||"尚未记录"}`,exp.id);card.append(button("更新实验记录",()=>edit("workspace.experiment.save",exp)));return card;
    }));
    $("decision-list").replaceChildren(...data.decision.map(d=>{const card=record(d.question,`备选方案：${d.options}\n标准：${d.criteria}\n选择：${d.chosen||"待决定"}\n回访：${d.review_date||"未安排"}`,d.id);card.append(button("更新决策",()=>edit("workspace.decision.save",d)));return card;}));
    renderAnnotations();
    const profile=document.querySelector('[data-workspace-action="workspace.profile.save"]');
    if(profile.dataset.loaded!==String(data.stats.profile.revision||0)){
      for(const key of ["goal","stage","constraints","weekly_hours"])profile.elements[key].value=data.stats.profile[key]??"";
      profile.dataset.loaded=String(data.stats.profile.revision||0);
    }
    ResearchDesk.render(data,project);
  }
  function renderAnnotations(){
    const item=state.library?.find(x=>x.id===readerId),target=$("annotation-list");if(!target)return;
    target.replaceChildren(...(state.annotation||[]).filter(a=>a.document_id===item?.document_id).map(a=>{
      const card=record(annotationKinds[a.kind]+(a.page?` · 第 ${a.page} 页`:""),a.text+(a.selection?"\n原文："+a.selection:""),a.id);card.append(button("编辑批注",()=>edit("workspace.annotation.save",a)));return card;
    }));
  }
  async function openReader(id){
    readerId=id;tab("workspace");$("workspace-reader").hidden=false;
    ResearchDesk.show("library");
    const data=await api(`/workspace/library/${id}/text`);$("reader-title").textContent=data.item.title;
    if(data.item.pdf_path){await PaperReader.open(data.item.document_id);return;}
    const page=$("reader-page");page.replaceChildren(new Option("全部正文",""));for(const n of data.pages)page.add(new Option("第 "+n+" 页",String(n)));
    async function show(){
      const value=page.value,body=await api(`/workspace/library/${id}/text${value?"?page="+value:""}`);
      $("reader-text").replaceChildren(...body.chunks.map(c=>{const p=node("p",c.text);p.dataset.chunkId=c.id;return p;}));
      document.querySelector('[data-workspace-action="workspace.annotation.save"] [name="page"]').value=value;
      const pdf=$("reader-pdf");pdf.hidden=!data.item.pdf_path;if(data.item.pdf_path)pdf.src=`/workspace/library/${id}/pdf#page=${value||1}`;
    }
    page.onchange=show;await show();renderAnnotations();
    async function prepareReading(){
      const quote=document.querySelector('[data-workspace-action="workspace.annotation.save"] [name="selection"]').value;
      await PaperReader.open(data.item.document_id);
      document.querySelector('[data-action="reading.ask"] [name="selection"]').value=quote;
      document.querySelector('[data-action="reading.ask"] [name="page"]').value=page.value;
      tab("reading");
    }
    $("reader-ask").onclick=()=>prepareReading().catch(e=>notice(e.message));
    $("reader-term").onclick=async()=>{
      await prepareReading();const term=document.querySelector('[data-workspace-action="workspace.annotation.save"] [name="text"]').value;
      document.querySelector('[data-action="reading.ask"] [name="question"]').value="请结合原文解释术语："+term+"。说明定义、适用条件和例子；证据不足时说明。";
    };
    $("reader-copy-selection").onclick=()=>{
      const selection=window.getSelection();if(!selection?.toString().trim())return notice("请先在正文中选中一段文字。");
      if(!$("reader-text").contains(selection.anchorNode)||!$("reader-text").contains(selection.focusNode))return notice("请在当前材料正文内选择文字。");
      document.querySelector('[data-workspace-action="workspace.annotation.save"] [name="selection"]').value=selection.toString();
    };
    const f=document.querySelector('[data-workspace-action="workspace.reading.log"]');f.elements.id.value=id;
    const annotationForm=document.querySelector('[data-workspace-action="workspace.annotation.save"]');
    if(annotationForm.dataset.document!==data.item.document_id){annotationForm.reset();annotationForm.elements.id.value="";annotationForm.elements.revision.value="";annotationForm.dataset.document=data.item.document_id;}
    $("workspace-reader").scrollIntoView({behavior:"smooth"});
  }
  function setup(){
    const logout=button("退出工作空间",async()=>{await api("/auth/logout",{});location.href="/login";});logout.hidden=true;
    document.querySelector("header").append(logout);
    api("/auth/status").then(status=>{logout.hidden=!status.required;}).catch(e=>notice(e.message));
    labels.workspace=["研究工作空间","把材料、阅读笔记、Idea、实验和个人汇报连接起来。"];
    const nav=node("button","研究驾驶舱");nav.dataset.tab="workspace";nav.onclick=()=>tab("workspace");document.querySelector("nav").prepend(nav);
    const root=node("section",undefined,"tab");root.id="workspace";document.querySelector("main").insertBefore(root,document.querySelector(".output"));
    const panel=node("div",undefined,"panel");panel.append(node("h2","当前研究方向"));
    const projectLabel=node("label","项目"),selector=node("select");selector.id="workspace-project";projectLabel.append(selector);panel.append(projectLabel);
    selector.onchange=()=>{project=selector.value;localStorage.setItem("research-project",project);readerId=null;$("workspace-reader").hidden=true;load().catch(e=>notice(e.message));};
    const daysLabel=node("label","最近天数"),days=node("input");days.id="workspace-days";days.type="number";days.min=1;days.max=366;days.value=7;daysLabel.append(days);panel.append(daysLabel,node("p","",undefined));
    const question=node("p");question.id="workspace-question";panel.append(question);days.onchange=()=>load().catch(e=>notice(e.message));
    for(const [title,action] of [["生成个人工作汇报","workspace.weekly"],["综合笔记与 Idea 候选","workspace.synthesize"],["习惯与决策建议","workspace.coach"]])panel.append(button(title,()=>act(action,{project_id:project||null,days:action==="workspace.coach"?Math.max(28,Number(days.value)):Number(days.value)})));
    const stats=node("div");stats.id="workspace-stats";panel.append(stats);root.append(panel);
    function addForm(title,f,open=false){const d=section(title,open);d.append(f);root.append(d);return f;}
    const pf=addForm("创建或修改研究项目",form("workspace.project.save","研究项目",[["名称","name"],["研究问题","question","textarea"],["关键词（逗号分隔）","keywords"],["目标会议/期刊","venues"],["下一步","next_step","textarea"],["状态","status","text",{active:"进行中",paused:"暂停",completed:"已完成"}]],false));
    pf.append(button("编辑当前项目",()=>{const p=state.projects.find(p=>p.id===project);if(p)edit("workspace.project.save",p);}));
    const industryForm=addForm("导入工程博客或官方报告",form("workspace.import","导入行业材料",[["文章 URL 或本地路径","source"],["标题（可选）","title"],["也可粘贴正文","text","textarea"],["组织/作者","organization"],["已核对的发布日期（可选）","published_at","date"],["类型","kind","text",types]]));industryForm.elements.kind.value="industry";
    const old=form("workspace.library.add","归档已有论文或文档",[["论文 ID（可选）","paper_id"],["文档 ID（可选）","document_id"],["类型","kind","text",types],["标签","tags"]]);addForm("归档已有材料",old);
    uploadControl(industryForm);uploadControl(document.querySelector('[data-action="documents.import"]'));
    const lib=section("材料库与阅读队列",true),list=node("div");list.id="library-list";lib.append(list);root.append(lib);
    addForm("整理材料信息",form("workspace.library.update","材料分类与状态",[["状态","status","text",stages],["标签","tags"],["归档会场分类（不代表录用核验）","venue"],["组织","organization"],["来源核验","source_status","text",{unverified:"未核验",official_domain:"官方域名",user_confirmed:"本人核对"}]]));
    const reader=node("div",undefined,"panel");reader.id="workspace-reader";reader.hidden=true;const title=node("h2");title.id="reader-title";reader.append(title);
    const pageLabel=node("label","正文页码"),page=node("select");page.id="reader-page";pageLabel.append(page);reader.append(pageLabel);
    const text=node("div",undefined,"workspace-reader-text");text.id="reader-text";reader.append(text);
    const pdfDetails=section("查看归档 PDF"),pdf=node("iframe");pdf.id="reader-pdf";pdf.title="论文 PDF";pdfDetails.append(pdf);reader.append(pdfDetails);
    const quote=button("将正文选段填入批注",()=>{});quote.id="reader-copy-selection";reader.append(quote);
    const ann=form("workspace.annotation.save","写批注或术语卡",[["类型","kind","text",annotationKinds],["原文选段","selection","textarea"],["页码（可选）","page","number"],["个人批注 / 术语","text","textarea"],["标签","tags"],["问题状态","resolved","text",{false:"待跟进",true:"已解决"}]]);reader.append(ann);
    const ask=button("带选段去问阅读助手",()=>{});ask.id="reader-ask";const term=button("查询这个专业术语",()=>{});term.id="reader-term";reader.append(ask,term,node("p","术语解释返回后，可显式保存到知识库；个人批注与模型回答分开保留。"));
    const logs=form("workspace.reading.log","记录本次阅读",[["本人确认的阅读分钟数","minutes","number"],["本次收获或阻塞","reflection","textarea"]],false);logs.elements.minutes.min=1;logs.elements.minutes.max=600;reader.append(logs);
    const annotations=node("div");annotations.id="annotation-list";reader.append(annotations);root.append(reader);
    const idea=form("workspace.idea.save","Idea 草稿",[["标题","title"],["问题","problem","textarea"],["可检验假设","hypothesis","textarea"],["与已有工作的差异","difference","textarea"],["来源笔记（可多选）","source_ids","text",{}],["风险和未知","risks","textarea"],["下一步","next_step","textarea"],["阶段","status","text",ideaStages],["新颖性核验","novelty_status","text",{unchecked:"待核验",user_reviewed:"本人已复核"}]]);idea.elements.source_ids.multiple=true;idea.elements.source_ids.size=5;addForm("创建或修改 Idea",idea);
    const ideas=section("我的 Idea",true),ideasList=node("div");ideasList.id="idea-list";ideas.append(ideasList);root.append(ideas);
    addForm("实验方案与结果",form("workspace.experiment.save","设计最小验证实验",[["关联 Idea","idea_id","text",{}],["实验名称","title"],["基线","baseline","textarea"],["数据与划分","dataset","textarea"],["评价指标","metrics","textarea"],["控制变量","controls","textarea"],["消融实验","ablations","textarea"],["资源预算","budget"],["停止条件","stopping_rule","textarea"],["预期结果（假设）","expected_result","textarea"],["实际结果","actual_result","textarea"],["状态","status","text",experimentStages]]));
    const exps=section("实验记录",true),expList=node("div");expList.id="experiment-list";exps.append(expList);root.append(exps);
    const decision=form("workspace.decision.save","记录一个需要复盘的决策",[["决策问题","question","textarea"],["备选方案及得失","options","textarea"],["评价标准与约束","criteria","textarea"],["依据笔记（可多选）","evidence_ids","text",{}],["目前选择","chosen"],["回访日期","review_date","date"]]);decision.elements.evidence_ids.multiple=true;decision.elements.evidence_ids.size=4;addForm("方向与投入决策",decision);
    const decisions=section("决策回访"),decisionList=node("div");decisionList.id="decision-list";decisions.append(decisionList);root.append(decisions);
    addForm("个人目标与约束",form("workspace.profile.save","习惯建议的参考信息",[["当前目标","goal","textarea"],["当前阶段","stage"],["时间、资源和个人约束","constraints","textarea"],["每周计划投入小时（可选）","weekly_hours","number"]],false));
    const search=document.querySelector('[data-action="papers.search"]');field(search,"目标会场（逗号分隔，例如 ICML,NeurIPS）","venues");field(search,"出版机构","publisher","text",{"":"不限",IEEE:"IEEE"});field(search,"会场证据范围","include_claimed","text",{false:"仅来源标注",true:"包含作者录用声明"});
    ResearchDesk.install(root,{edit,openReader,act});
    for(const [key,title] of Object.entries({"project.save":"保存项目","library.add":"归档材料","library.acquire":"分类下载与导入","import":"导入行业材料","annotation.save":"保存批注","idea.save":"保存 Idea","experiment.save":"记录实验","weekly":"个人工作汇报","synthesize":"研究综合","coach":"习惯建议","reading.log":"阅读记录","library.update":"整理材料","profile.save":"个人目标","decision.save":"决策记录","stats":"工作统计"}))actionNames["workspace."+key]=title;
  }
  function display(result,target){
    if(result.entry?.hypothesis||result.entry?.idea_id)ResearchDesk.show("ideas");
    else if(result.entry?.name||["paper","industry"].includes(result.entry?.kind)&&result.entry?.document_id)ResearchDesk.show("library");
    if(result.message)target.append(record("工作空间提示",result.message));
    if(result.markdown){const d=node("details");d.open=true;d.append(node("summary","个人工作汇报"),node("pre",result.markdown));target.append(d);}
    if(result.synthesis){const s=result.synthesis;target.append(record("研究进展综合",s.overview));
      for(const row of [...s.findings,...s.disagreements])target.append(record("笔记证据",row.text,row.source_ids.join(", ")));
      for(const idea of s.candidate_ideas){const card=record("候选 Idea · "+idea.title,`${idea.hypothesis}\n差异：${idea.difference}\n验证：${idea.validation}\n不确定性：${idea.uncertainty}`,idea.source_ids.join(", "));
        card.append(button("采纳为 Idea 草稿",()=>act("workspace.idea.save",{project_id:selected(),title:idea.title,hypothesis:idea.hypothesis,difference:idea.difference,source_ids:idea.source_ids,next_step:idea.validation,risks:idea.uncertainty})));target.append(card);}
      for(const q of s.questions)target.append(record("待跟进问题",q));
    }
    if(result.advice){for(const item of result.advice.observations)target.append(record("基于记录的观察",item.interpretation,item.metric_keys.join(", ")));for(const item of result.advice.options)target.append(record("行动选项",`${item.action}\n收益：${item.benefit}\n代价：${item.cost}\n不确定性：${item.uncertainty}`));target.append(record("试行与复盘",result.advice.trial_plan));}
    if(result.metrics){const box=node("div");statsView(box,result);target.append(box);}
  }
  async function addPaper(paper){await act("workspace.library.add",{project_id:selected(),paper_id:paper.id});}
  return {setup,load,display,addPaper};
})();
