/** Keep keyboard navigation inside an open dialog and restore the previous focus. */
export function focusDialog(node:HTMLElement,onclose:()=>void){
 const previous=document.activeElement as HTMLElement|null;
 const focusable=()=>Array.from(node.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),[tabindex="0"]')).filter(el=>el.getClientRects().length>0);
 queueMicrotask(()=>focusable()[0]?.focus());
 function keydown(e:KeyboardEvent){
  if(e.key==='Escape'){e.stopPropagation();onclose();return;}
  if(e.key!=='Tab')return;
  const items=focusable(),first=items[0],last=items.at(-1);
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
 }
 node.addEventListener('keydown',keydown);
 return {destroy(){node.removeEventListener('keydown',keydown);previous?.focus();}};
}
