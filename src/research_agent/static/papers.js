"use strict";
window.ResearchPapers = (() => {
  const ns="http://www.w3.org/2000/svg";
  function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
  function svgEl(tag,attrs){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);return e;}
  function link(url,title){const a=el("a",title);try{const u=new URL(url);if(!["https:","http:"].includes(u.protocol))return null;a.href=u.href;}catch{return null;}a.target="_blank";a.rel="noopener noreferrer";return a;}
  function pdfUrl(p){return p.pdf_url || (p.arxiv_id ? "https://arxiv.org/pdf/"+encodeURIComponent(p.arxiv_id) : "");}
  function card(p,actions={}){
    const box=el("article",undefined,"record paper-card");box.dataset.paperId=p.id;
    box.append(el("h3",p.title),el("small",`${p.year || "年份未知"} · ${(p.authors || []).join(", ")} · ${p.source_ids?.browser?"浏览器采集 · 被引数未知":"数据源被引数 "+(p.citation_count ?? "未知")}`));
    if(p.abstract)box.append(el("p",p.abstract));
    const buttons=el("div",undefined,"paper-actions");
    const source=link(p.url,"阅读原文 ↗");if(source)buttons.append(source);
    if(pdfUrl(p)){
      if(actions.onRead){const b=el("button","在线阅读与提问");b.onclick=()=>Promise.resolve(actions.onRead(p)).catch(e=>notice(e.message));buttons.append(b);}
      if(actions.onDownload){const b=el("button","下载 PDF");b.onclick=()=>actions.onDownload(p);buttons.append(b);}
      const a=link(pdfUrl(p),actions.onDownload?"打开 PDF ↗":"打开 / 下载 PDF ↗");if(a)buttons.append(a);
    }else buttons.append(el("span","暂无开放 PDF 地址","paper-muted"));
    if(actions.onExplore){const b=el("button","以此论文展开关系");b.onclick=()=>actions.onExplore(p);buttons.append(b);}
    if(actions.onMap){const b=el("button","生成文献相似图");b.onclick=()=>actions.onMap(p);buttons.append(b);}
    if(actions.onAdd){const b=el("button","加入当前项目材料库");b.onclick=()=>Promise.resolve(actions.onAdd(p)).catch(e=>notice(e.message));buttons.append(b);}
    if(p.venue)box.append(el("small",`来源会场：${p.venue} · ${p.venue_status==="author_claim"?"作者声明，待核验":p.venue_status==="indexed"?"来源元数据标注":"未核验"}${p.publisher?" · "+p.publisher:""}`));
    box.append(buttons);return box;
  }
  function mount(target,data,actions={}){
    if(data.graph_type==="bibliometric"){ResearchMap.mount(target,data,actions);return;}
    const wrapper=el("section",undefined,"paper-explorer");target.append(wrapper);
    for(const portal of data.venue_links||[]){const a=link(portal.url,portal.venue+" 官方论文入口 ↗");if(a)wrapper.append(a,el("span","　"));}
    if(data.search_pages?.length){
      wrapper.append(el("h3","本地 Chrome 搜索来源"));
      for(const page of data.search_pages){const row=el("p",`${page.site} · ${page.status==="completed"?"已读取 "+page.count+" 条":"未完成"} · `),a=link(page.url,"打开搜索页 ↗");if(a)row.append(a);wrapper.append(row);}
    }
    if(!data.seed || !data.relations){
      if(data.status==="needs_selection")wrapper.append(el("h2","找到多个候选，请选择论文"));
      const papers=data.candidates || data.papers || [];
      for(const p of papers)wrapper.append(card(p,actions));
      if(!papers.length)wrapper.append(el("p","本次未返回论文，请检查数据提示或调整关键词。"));
      return;
    }
    const seed=data.seed.id, map=new Map(data.papers.map(p=>[p.id,p]));map.set(seed,data.seed);
    const relations=data.relations.filter(e=>map.has(e.source)&&map.has(e.target));
    const refs=new Set(relations.filter(e=>e.kind==="cites"&&e.source===seed).map(e=>e.target));
    const citing=new Set(relations.filter(e=>e.kind==="cites"&&e.target===seed).map(e=>e.source));
    const similar=new Set(relations.filter(e=>e.kind==="similar").flatMap(e=>[e.source,e.target]).filter(id=>id!==seed));
    wrapper.append(el("h2","论文引用关系图"),el("p","箭头从引用者指向被引用者：引用本文 → 中心论文 → 参考文献。橙色虚线仅表示文本相似推荐，不代表引用。"));
    wrapper.append(el("p",`当前页：参考文献 ${refs.size} 篇 · 引用本文 ${citing.size} 篇 · 相似推荐 ${similar.size} 篇。数据源被引总数 ${data.seed.citation_count ?? "未知"}，不等于本图已加载数量。`));
    const toolbar=el("div",undefined,"paper-toolbar"),label=el("label","关系筛选"),filter=el("select");filter.setAttribute("aria-label","关系筛选");
    for(const [value,title] of [["all","全部关系"],["references","中心论文的参考文献"],["citations","引用中心论文"],["similar","相似推荐"]])filter.add(new Option(title,value));
    label.append(filter);toolbar.append(label);
    const stage=el("div",undefined,"paper-graph-stage"),svg=svgEl("svg",{role:"img","aria-label":"引用关系图，箭头由引用者指向被引用者"});stage.append(svg);
    const detail=el("div",undefined,"paper-selected");
    let positions=new Map(), selected=seed, zoom=1, drag=null, height=500;
    function position(){
      const left=[...refs],right=[...citing].filter(id=>!refs.has(id));
      const bottom=[...similar].filter(id=>!refs.has(id)&&!citing.has(id));
      const mainHeight=Math.max(280,Math.max(left.length,right.length)*65+80);
      height=mainHeight+Math.ceil(bottom.length/3)*65+100;
      positions=new Map([[seed,{x:500,y:mainHeight/2}]]);
      left.forEach((id,i)=>positions.set(id,{x:170,y:80+i*65}));
      right.forEach((id,i)=>positions.set(id,{x:800,y:80+i*65}));
      bottom.forEach((id,i)=>positions.set(id,{x:150+(i%3)*330,y:mainHeight+65*Math.floor(i/3)+40}));
    }
    function select(id){selected=id;detail.replaceChildren(el("h3",id===seed?"中心论文":"选中论文"),card(map.get(id),actions));draw();}
    function allowed(e){return filter.value==="all" || (filter.value==="similar"?e.kind==="similar":e.kind==="cites"&&(filter.value==="references"?e.source===seed:e.target===seed));}
    function draw(){
      svg.replaceChildren();svg.setAttribute("viewBox",`0 0 1100 ${height}`);svg.style.width=`${zoom*100}%`;svg.style.height=`${height*zoom}px`;
      const defs=svgEl("defs",{}),marker=svgEl("marker",{id:"citation-arrow",viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:7,markerHeight:7,orient:"auto"});marker.append(svgEl("path",{d:"M0 0L10 5L0 10Z",fill:"#3267a8"}));defs.append(marker);svg.append(defs);
      for(const [x,text] of [[110,"参考文献（中心论文引用）"],[730,"引用本文（后续引用者）"]]){const t=svgEl("text",{x,y:26,fill:"#476454"});t.textContent=text;svg.append(t);}
      const visible=relations.filter(allowed),ids=new Set([seed,...visible.flatMap(e=>[e.source,e.target])]);
      for(const e of visible){
        const a=positions.get(e.source),b=positions.get(e.target);if(!a||!b)continue;
        const dx=b.x-a.x,dy=b.y-a.y,length=Math.hypot(dx,dy)||1, radius=e.target===seed?21:13;
        const line=svgEl("line",{x1:a.x,y1:a.y,x2:b.x-dx/length*radius,y2:b.y-dy/length*radius,
          stroke:e.kind==="similar"?"#b67b28":"#3267a8","stroke-width":e.source===selected||e.target===selected?2.5:1,
          "stroke-dasharray":e.kind==="similar"?"6 5":"none",opacity:e.source===selected||e.target===selected?1:0.4});
        line.dataset.source=e.source;line.dataset.target=e.target;line.dataset.kind=e.kind;
        if(e.kind==="cites")line.setAttribute("marker-end","url(#citation-arrow)");
        const title=svgEl("title",{});title.textContent=`${map.get(e.source).title} ${e.kind==="cites"?"引用":"相似于"} ${map.get(e.target).title}`;line.append(title);svg.append(line);
      }
      for(const id of ids){
        const p=map.get(id),pos=positions.get(id);if(!pos)continue;
        const g=svgEl("g",{tabindex:0,role:"button","aria-label":p.title});g.dataset.paperId=id;
        const c=svgEl("circle",{cx:pos.x,cy:pos.y,r:id===seed?20:12,fill:id===seed?"#183f35":refs.has(id)?"#45816e":citing.has(id)?"#3267a8":"#b67b28",stroke:id===selected?"#ebad42":"white","stroke-width":3});
        const title=svgEl("title",{});title.textContent=p.title;c.append(title);g.append(c);
        const t=svgEl("text",{x:pos.x+17,y:pos.y+4,"font-size":12});t.textContent=`${p.year||"?"} · ${p.title.slice(0,24)}${p.title.length>24?"…":""}`;g.append(t);
        g.onclick=()=>select(id);g.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();select(id);}};
        g.onpointerdown=e=>{drag=id;svg.setPointerCapture(e.pointerId);};svg.append(g);
      }
    }
    svg.onpointermove=e=>{if(!drag)return;const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const p=pt.matrixTransform(svg.getScreenCTM().inverse());positions.set(drag,{x:Math.max(25,Math.min(1000,p.x)),y:Math.max(45,Math.min(height-30,p.y))});draw();};
    svg.onpointerup=()=>{if(drag)select(drag);drag=null;};svg.onpointercancel=()=>drag=null;
    for(const [name,fn] of [["放大",()=>zoom=Math.min(2.5,zoom+0.25)],["缩小",()=>zoom=Math.max(0.5,zoom-0.25)],["重置布局",()=>{zoom=1;position();}]]){const b=el("button",name);b.onclick=()=>{fn();draw();};toolbar.append(b);}
    filter.onchange=draw;wrapper.append(toolbar,stage,detail);position();select(seed);
    for(const [key,title,ids] of [["references","参考文献 · 中心论文引用的论文",refs],["citations","引用本文 · 引用了中心论文的论文",citing],["similar","相似论文 · 文本相似推荐",similar]]){
      const group=el("details",undefined,"paper-group");group.dataset.direction=key;group.open=true;
      group.append(el("summary",`${title}（本页 ${ids.size}）`));
      for(const id of ids)group.append(card(map.get(id),actions));
      if(!ids.size)group.append(el("p","本页未加载该类关系；这不代表不存在引用，请结合数据提示检查覆盖范围。"));
      const next=data.pagination?.[key]?.next_offset;
      if(next!==null&&next!==undefined){group.append(el("p","当前展示部分结果，仍有后续页面。"));if(actions.onPage){const b=el("button",key==="references"?"下一页参考文献":"下一页引用本文");b.onclick=()=>actions.onPage(key,next);group.append(b);}}
      wrapper.append(group);
    }
  }
  return {mount,card};
})();
