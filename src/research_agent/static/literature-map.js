"use strict";
window.ResearchMap=(()=>{
  const ns="http://www.w3.org/2000/svg";
  function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
  function shape(tag,attrs){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);return e;}
  function mount(target,data,actions={}){
    const section=el("section",undefined,"literature-map"),papers=new Map(data.papers.map(p=>[p.id,p]));target.append(section);
    const root=data.seed.id,edges=data.relations,covers=data.coverage;
    section.append(el("h2","共引与文献耦合相似图"),el("p","连线越粗，观测到的引用结构越相似。相似连线没有方向；点击连线可查看共同来源。节点大小表示被引数，颜色由蓝到绿表示发表时间由早到晚，灰色表示年份未知。"));
    const missing=covers.neighborhoods.filter(n=>!n.references.complete||!n.citations.complete).length;
    section.append(el("p",`来源 ${covers.provider} · 发现 ${covers.candidate_count} 篇候选 · 评估 ${covers.evaluated_count} 篇 · 显示 ${covers.shown_count} 篇 · ${missing} 篇邻域不完整。每次扩展最多取 ${covers.sample_size} 条记录，当前是采样结果。`,"map-coverage"));
    const controls=el("div",undefined,"paper-toolbar"),label=el("label","连线依据"),filter=el("select");filter.setAttribute("aria-label","相似连线依据");
    for(const [v,t] of [["both","综合相似度"],["coupling","文献耦合 · 共享参考文献"],["cocitation","共引 · 共同引用者"],["citations","真实引用 · 有向箭头"]])filter.add(new Option(t,v));label.append(filter);controls.append(label);
    const cutoffLabel=el("label","最低分数"),cutoff=el("input");cutoff.type="range";cutoff.min=0;cutoff.max=1;cutoff.step=.05;cutoff.value=0;cutoff.setAttribute("aria-label","最低相似分数");const readout=el("span","0.00");cutoffLabel.append(cutoff,readout);controls.append(cutoffLabel);
    const stage=el("div",undefined,"paper-graph-stage map-stage"),svg=shape("svg",{viewBox:"0 0 1000 650",role:"img","aria-label":"共引和文献耦合相似图"});stage.append(svg);
    const detail=el("div",undefined,"paper-selected map-detail");
    let positions=new Map(),selected=root,drag=null,zoom=1;
    const years=data.papers.map(p=>p.year).filter(Boolean),minYear=Math.min(...years),maxYear=Math.max(...years);
    function radius(p){return p.id===root?21:Math.min(19,7+Math.log2(1+(p.citation_count||0)))}
    function color(p){return p.year?`hsl(${220-80*(p.year-minYear)/Math.max(1,maxYear-minYear)} 48% 43%)`:"#8c9690";}
    function layout(){
      const list=data.papers;positions=new Map(list.map((p,i)=>[p.id,{x:500+220*Math.cos(i*2*Math.PI/list.length),y:325+220*Math.sin(i*2*Math.PI/list.length)}]));positions.set(root,{x:500,y:325});
      for(let step=0;step<180;step++){
        const forces=new Map(list.map(p=>[p.id,{x:0,y:0}]));
        for(let i=0;i<list.length;i++)for(let j=i+1;j<list.length;j++){
          const a=positions.get(list[i].id),b=positions.get(list[j].id),dx=a.x-b.x,dy=a.y-b.y,d=Math.max(15,Math.hypot(dx,dy)),force=1700/(d*d);
          forces.get(list[i].id).x+=dx/d*force;forces.get(list[i].id).y+=dy/d*force;forces.get(list[j].id).x-=dx/d*force;forces.get(list[j].id).y-=dy/d*force;
        }
        for(const edge of edges){const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)continue;const dx=b.x-a.x,dy=b.y-a.y,d=Math.max(1,Math.hypot(dx,dy)),force=(d-(85+170*(1-edge.score)))*.015;forces.get(edge.source).x+=dx/d*force;forces.get(edge.source).y+=dy/d*force;forces.get(edge.target).x-=dx/d*force;forces.get(edge.target).y-=dy/d*force;}
        for(const p of list){if(p.id===root)continue;const pos=positions.get(p.id),f=forces.get(p.id);pos.x=Math.max(50,Math.min(850,pos.x+Math.max(-8,Math.min(8,f.x))));pos.y=Math.max(50,Math.min(600,pos.y+Math.max(-8,Math.min(8,f.y))));}
      }
    }
    function metric(edge){return filter.value==="coupling"?edge.coupling_score:filter.value==="cocitation"?edge.co_citation_score:edge.score;}
    function showEvidence(edge){
      detail.replaceChildren(el("h3",`${papers.get(edge.source).title} ↔ ${papers.get(edge.target).title}`));
      detail.append(el("p",`综合 ${edge.score.toFixed(3)} · 文献耦合 ${edge.coupling_score.toFixed(3)} · 共引 ${edge.co_citation_score.toFixed(3)}`));
      for(const [key,count,title] of [["shared_reference_ids",edge.shared_reference_count,"共享参考文献"],["shared_citing_ids",edge.shared_citing_count,"共同引用者"]]){
        detail.append(el("h3",`${title}：${count} 篇${count>20?"（列出前 20 篇）":""}`));
        if(!count)detail.append(el("p","当前样本未观察到。"));
        for(const id of edge[key]){const p=data.evidence_papers[id];if(p)detail.append(ResearchPapers.card(p,actions));else detail.append(el("p",id));}
      }
    }
    function select(id){selected=id;detail.replaceChildren(el("h3",id===root?"起点论文":"选中论文"),ResearchPapers.card(papers.get(id),actions));
      for(const edge of edges.filter(e=>e.source===id||e.target===id).sort((a,b)=>b.score-a.score)){const other=edge.source===id?edge.target:edge.source,b=el("button",`${papers.get(other).title} · 相似度 ${edge.score.toFixed(3)} · 查看共同来源`);b.onclick=()=>showEvidence(edge);detail.append(b);}
      draw();
    }
    function draw(){
      svg.replaceChildren();svg.style.width=`${zoom*100}%`;svg.style.height=`${650*zoom}px`;
      const defs=shape("defs",{}),marker=shape("marker",{id:"map-citation-arrow",viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:7,markerHeight:7,orient:"auto"});marker.append(shape("path",{d:"M0 0L10 5L0 10Z",fill:"#3267a8"}));defs.append(marker);svg.append(defs);
      const visible=filter.value==="citations"?data.citation_relations:edges.filter(e=>metric(e)>0&&metric(e)>=Number(cutoff.value));
      for(const edge of visible){const a=positions.get(edge.source),b=positions.get(edge.target),direct=edge.kind==="cites",dx=b.x-a.x,dy=b.y-a.y,length=Math.max(1,Math.hypot(dx,dy)),r=radius(papers.get(edge.target));
        const line=shape("line",{x1:a.x,y1:a.y,x2:direct?b.x-dx/length*(r+2):b.x,y2:direct?b.y-dy/length*(r+2):b.y,stroke:direct?"#3267a8":filter.value==="coupling"?"#45816e":filter.value==="cocitation"?"#3267a8":"#795ba7","stroke-width":direct?2:1+5*metric(edge),opacity:edge.source===selected||edge.target===selected?1:.4,tabindex:0,role:"button","aria-label":direct?"真实引用":"查看相似连线的共同来源"});
        line.dataset.source=edge.source;line.dataset.target=edge.target;line.dataset.kind=edge.kind;
        const title=shape("title",{});title.textContent=direct?`${papers.get(edge.source).title} 引用 ${papers.get(edge.target).title}`:`共享参考文献 ${edge.shared_reference_count} · 共同引用者 ${edge.shared_citing_count}`;line.append(title);
        if(direct)line.setAttribute("marker-end","url(#map-citation-arrow)");else{line.onclick=()=>showEvidence(edge);line.onkeydown=e=>{if(e.key==="Enter")showEvidence(edge);};}svg.append(line);
      }
      for(const p of data.papers){const pos=positions.get(p.id),g=shape("g",{tabindex:0,role:"button","aria-label":p.title});g.dataset.paperId=p.id;
        const circle=shape("circle",{cx:pos.x,cy:pos.y,r:radius(p),fill:color(p),stroke:p.id===selected?"#ebad42":"#fff","stroke-width":3}),title=shape("title",{});title.textContent=`${p.title} · ${p.year||"年份未知"} · 被引 ${p.citation_count||0}`;circle.append(title);g.append(circle);
        const text=shape("text",{x:pos.x+radius(p)+4,y:pos.y+4,"font-size":12});text.textContent=p.title.slice(0,22)+(p.title.length>22?"…":"");g.append(text);
        g.onclick=()=>select(p.id);g.onkeydown=e=>{if(e.key==="Enter"){select(p.id);}};g.onpointerdown=e=>{drag=p.id;svg.setPointerCapture(e.pointerId);};svg.append(g);
      }
      readout.textContent=Number(cutoff.value).toFixed(2)+` · ${visible.length} 条连线`;
    }
    svg.onpointermove=e=>{if(!drag)return;const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());positions.set(drag,{x:Math.max(30,Math.min(900,p.x)),y:Math.max(30,Math.min(610,p.y))});draw();};svg.onpointerup=()=>{if(drag)select(drag);drag=null;};svg.onpointercancel=()=>drag=null;
    for(const [title,fn] of [["放大",()=>zoom=Math.min(2.5,zoom+.25)],["缩小",()=>zoom=Math.max(.5,zoom-.25)],["重新布局",()=>{layout();zoom=1;}]]){const b=el("button",title);b.onclick=()=>{fn();draw();};controls.append(b);}
    filter.onchange=()=>{cutoff.disabled=filter.value==="citations";draw();};cutoff.oninput=draw;
    section.append(controls,stage,detail);layout();select(root);
    for(const [key,title,description] of [["prior_works","共同前作","被图中多篇论文引用的共同基础文献。"],["derivative_works","共同后续","引用图中多篇论文的后续工作；仅反映已观察到的引用。"]]){
      const group=el("details",undefined,"paper-group");group.dataset.mapGroup=key;group.open=true;group.append(el("summary",`${title}（${data[key].length}）`),el("p",description));
      for(const row of data[key]){const box=ResearchPapers.card(row.paper,actions);box.prepend(el("p",`关联图中 ${row.support_count} 篇论文：${row.graph_paper_ids.map(i=>papers.get(i).title).join("；")}`));group.append(box);}
      if(!data[key].length)group.append(el("p","当前样本没有符合条件的论文。"));section.append(group);
    }
    const table=el("details");table.append(el("summary","查看全部图中论文"));for(const p of [...data.papers].sort((a,b)=>b.similarity_to_origin_path-a.similarity_to_origin_path))table.append(ResearchPapers.card(p,actions));section.append(table);
    const method=el("details");method.append(el("summary","计算方法与采样覆盖"),el("p",data.method.description),el("pre",data.method.formula),el("pre",JSON.stringify(data.coverage,null,2)));section.append(method);
  }
  function setup(){
    const searchForm=document.querySelector('form[data-action="papers.search"]');
    const modeLabel=el("label","检索方式"),mode=el("select");mode.name="mode";
    for(const [value,title] of [["auto","自动 · API 限流时用本地浏览器"],["arxiv_browser","本地 Chrome · arXiv"],["google_research_browser","本地 Chrome · Google Research"],["browser","本地 Chrome · 两个来源"],["api","仅使用 API"]])mode.add(new Option(title,value));
    modeLabel.append(mode);searchForm.insertBefore(modeLabel,searchForm.querySelector('button'));
    const form=el("form");form.append(el("h2","构建文献相似图"),el("p","基于共引和文献耦合，发现不直接互相引用的相关论文。构建可能需要数十秒，结果会保存到任务记录。"));
    function field(title,name,value,type="text"){const label=el("label",title),input=el("input");input.name=name;input.value=value;input.type=type;input.required=true;label.append(input);form.append(label);return input;}
    const seed=field("起点论文：论文 ID、DOI、arXiv ID 或完整标题","seed","");seed.id="map-seed";
    const limit=field("最多显示论文数","limit",20,"number");limit.min=2;limit.max=40;
    const candidates=field("评估候选数（含起点）","candidate_limit",24,"number");candidates.min=3;candidates.max=40;
    const sample=field("每次扩展的引用样本数","sample_size",50,"number");sample.min=5;sample.max=100;
    const button=el("button","生成相似图 →","primary");button.type="submit";form.append(button);
    form.onsubmit=async e=>{e.preventDefault();if(Number(limit.value)>Number(candidates.value)){notice("展示数量不能超过评估候选数量");return;}button.disabled=true;try{await submitPaper("papers.map",{seed:seed.value.trim(),limit:Number(limit.value),candidate_limit:Number(candidates.value),sample_size:Number(sample.value)});}finally{button.disabled=false;}};
    document.getElementById("papers").append(form);
  }
  return {mount,setup};
})();
