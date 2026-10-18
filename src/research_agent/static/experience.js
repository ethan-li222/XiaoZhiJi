"use strict";
window.WorkbenchExperience=(()=>{
  function fold(form,inputs,title){const details=document.createElement("details"),summary=document.createElement("summary");summary.textContent=title;details.append(summary);for(const input of inputs){const part=typeof input==="string"?form.querySelector(input):input;if(part)details.append(part);}form.insertBefore(details,form.querySelector("button.primary"));}
  function install(){
    const start=document.createElement("div");start.className="reading-start";start.dataset.deskArea="overview";
    const caption=document.createElement("p");caption.textContent="日常流程：找论文 → 阅读与选段提问 → 保存笔记 → 汇报；研究项目可按需建立。";start.append(caption);
    for(const [title,target] of [["开始找论文","papers"],["打开阅读库","reading"]]){const b=document.createElement("button");b.type="button";b.textContent=title;b.onclick=()=>tab(target);start.append(b);}document.querySelector("#workspace .desk-tabs").after(start);
    const names={papers:"找论文",reading:"阅读",knowledge:"知识与记忆",reports:"前沿动态",slides:"工作汇报",tasks:"任务记录"};for(const b of document.querySelectorAll("nav [data-tab]"))if(names[b.dataset.tab])b.textContent=names[b.dataset.tab];
    for(const [name,text] of Object.entries(names))labels[name][0]=text;
    const search=document.querySelector('[data-action="papers.search"]');fold(search,[search.querySelector(".row"),...Array.from(search.querySelectorAll("label")).filter(l=>l.querySelector('[name="mode"],[name="venues"],[name="publisher"],[name="include_claimed"]'))],"筛选与检索方式");
    const paperGrid=$("papers").querySelector(".grid");paperGrid.classList.add("discovery-layout");
    for(const form of $("papers").querySelectorAll("form"))if(form!==search){const d=document.createElement("details"),s=document.createElement("summary");s.textContent=form.querySelector("h2")?.textContent||"文献关系工具";form.before(d);d.append(s,form);}
    for(const action of ["knowledge.save","reports.generate","slides.outline","slides.revise"]){const form=document.querySelector(`[data-action="${action}"]`);if(!form)continue;const d=document.createElement("details"),s=document.createElement("summary");s.textContent=form.querySelector("h2").textContent;form.before(d);d.className="tool-disclosure";d.append(s,form);}
    const build=document.querySelector('[data-action="slides.build"]');fold(build,[build.querySelector("label")],"高级编辑：演示稿 JSON");
    const preview=document.createElement("div");preview.id="slide-readable-preview";build.prepend(preview);
    const deck=$("deck");function render(){preview.replaceChildren();try{const data=JSON.parse(deck.value);for(const [i,slide] of data.slides.entries()){const card=document.createElement("article"),title=document.createElement("h3"),text=document.createElement("p");title.textContent=`${i+1}. ${slide.title}`;text.textContent=slide.bullets.join("\n");card.append(title,text);preview.append(card);}}catch{preview.textContent="从研究驾驶舱生成个人工作汇报，或选择已有报告生成大纲。确认内容后制作 PPT。";}}
    deck.addEventListener("input",render);render();
    return {renderSlides:render};
  }
  return {install};
})();
