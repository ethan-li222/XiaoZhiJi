"use strict";
const memoryStatus = {inbox:"待整理", confirmed:"已确认", archived:"已归档"};
async function memoryAction(action, params){
  notice("");
  try { const task = await api("/tasks", {action, params}); await watch(task.task_id); }
  catch(error){ notice(error.message); }
}
function knowledgeCard(k){
  const el = record(k.question, k.answer, k.id);
  el.dataset.memoryStatus = k.status || "inbox";
  el.dataset.memoryTags = JSON.stringify(k.tags || []);
  el.append(node("small", `${memoryStatus[k.status || "inbox"]} · ${(k.tags || []).join(" / ")} · 版本 ${k.revision || 1}`));
  if(k.notes) el.append(record("个人批注", k.notes));
  const sources = node("details");
  sources.append(node("summary", "查看原文依据"));
  for(const source of k.evidence || []){
    const part = record(source.title, source.text, `原文块 ${source.id} · 页码 ${source.page || "—"}`);
    if(source.source) part.append(link(source.source, source.source));
    sources.append(part);
  }
  el.append(sources);
  const edit = node("details"); edit.append(node("summary", "整理卡片"));
  const form = node("form");
  function field(title, input){const label=node("label",title);label.append(input);form.append(label);return input;}
  const notes = field("个人批注（原回答和证据保留）", node("textarea")); notes.value=k.notes || "";notes.maxLength=12000;
  const tags = field("标签，用逗号分隔", node("input"));tags.value=(k.tags || []).join(", ");
  const status = field("状态", node("select"));
  for(const [value, title] of Object.entries(memoryStatus))status.add(new Option(title,value));
  status.value=k.status || "inbox";
  const save=node("button","保存整理","primary");save.type="submit";form.append(save);
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;
    try{await memoryAction("knowledge.update",{id:k.id,revision:k.revision || 1,notes:notes.value,
      tags:tags.value.split(/[,，]/).map(t=>t.trim()).filter(Boolean),status:status.value});}
    finally{save.disabled=false;}
  };
  edit.append(form);el.append(edit);return el;
}
function filterMemory(){
  const status=$("memory-filter").value,tag=$("memory-tag").value.trim();
  for(const el of $("knowledge-list").children){
    el.hidden=!!((status && el.dataset.memoryStatus!==status) ||
      (tag && !JSON.parse(el.dataset.memoryTags || "[]").includes(tag)));
  }
}
function renderReadingHistory(){
  const target=$("reading-history");if(!target)return;
  target.replaceChildren(node("h2","会话阅读记录"));
  const session=sessions.find(s=>s.id===$("sessions").value);
  if(!session){target.append(node("p","选择已有会话查看历史，或开始新会话。"));return;}
  for(const [index, turn] of session.history.entries()){
    const entry=record(`${index+1}. ${turn.question}`,turn.answer,turn.created_at || "");
    const save=node("button","将这一轮存入知识库");
    save.onclick=()=>memoryAction("knowledge.save",{session_id:session.id,turn:index});
    entry.append(save);target.append(entry);
  }
}
function setupMemory(){
  const history=node("div",undefined,"panel");history.id="reading-history";
  $("reading").append(history);$("sessions").addEventListener("change",renderReadingHistory);
  renderReadingHistory();
  const panel=node("div",undefined,"panel");panel.append(node("h2","整理与复盘"),
    node("p","新卡片进入待整理；核对后设为已确认，阅读助手才会召回。归档卡片不参与默认检索。"));
  const review=node("button","复盘最近 7 天"),exportButton=node("button","导出 Markdown / JSON");
  review.onclick=()=>memoryAction("knowledge.review",{days:7});
  exportButton.onclick=()=>memoryAction("knowledge.export",{});panel.append(review,exportButton);
  const label=node("label","卡片状态"),filter=node("select");filter.id="memory-filter";
  filter.add(new Option("全部状态",""));
  for(const [value,title] of Object.entries(memoryStatus))filter.add(new Option(title,value));
  label.append(filter);panel.append(label);
  const tagLabel=node("label","按标签筛选"),tag=node("input");tag.id="memory-tag";tagLabel.append(tag);panel.append(tagLabel);
  filter.onchange=filterMemory;tag.oninput=filterMemory;
  $("knowledge").insertBefore(panel,$("knowledge-list").parentElement);
  const search=document.querySelector('form[data-action="knowledge.search"]');
  const searchLabel=node("label","检索状态"),searchStatus=filter.cloneNode(true);
  searchStatus.removeAttribute("id");searchStatus.name="status";
  searchStatus.options[0].text="待整理与已确认";searchLabel.append(searchStatus);
  search.insertBefore(searchLabel,search.querySelector("button"));
}
