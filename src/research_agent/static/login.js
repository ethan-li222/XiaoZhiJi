"use strict";
document.getElementById("login-form").onsubmit=async event=>{
  event.preventDefault();const form=event.target,button=form.querySelector("button");button.disabled=true;
  try{const response=await fetch("/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:form.elements.token.value})});
    const body=await response.json();if(!response.ok)throw new Error(body.detail||"登录失败");location.href="/";
  }catch(error){document.getElementById("login-error").textContent=error.message;}finally{button.disabled=false;}
};
