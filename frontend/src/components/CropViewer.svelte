<script lang="ts">
 import {onMount} from 'svelte';
 import {MousePointer2,Hand,ScanLine,ZoomIn,ZoomOut,Maximize,Eye,EyeOff,Undo2,Redo2,Plus,Columns2,Merge} from '@lucide/svelte';
 import type {Page,Region} from '../types';
 import {toPage,normalizedBox} from '../utils/coordinates';
 let {jobId,page,regions,selected,onSelect,onEdit,onCreate,onHistory,onSplit,onMerge}: {jobId:string;page:Page;regions:Region[];selected:string[];onSelect:(id:string,multi?:boolean)=>void;onEdit:(id:string,bbox:number[])=>void;onCreate:(bbox:number[])=>void;onHistory:(redo:boolean)=>void;onSplit:()=>void;onMerge:()=>void}=$props();
 let container:HTMLDivElement,svg:SVGSVGElement;
 let zoom=$state(1),fit=$state(1),tool=$state('select'),overlays=$state(true);
 let draft=$state<number[]|null>(null),drag=$state<{id:string;handle:string;start:number[];box:number[]}|null>(null);
 let pan:{x:number;y:number;left:number;top:number}|null=null;
 let lastPage='';
 $effect(()=>{const key=jobId+page.number;if(key!==lastPage){lastPage=key;zoom=1;draft=null;drag=null;} });
 function resize(){if(container&&page)fit=Math.min((container.clientWidth-72)/page.width,(container.clientHeight-72)/page.height);}
 $effect(()=>{page; if(container)resize();});
 onMount(()=>{const observer=new ResizeObserver(resize);observer.observe(container);resize();return()=>observer.disconnect();});
 const point=(e:PointerEvent)=>toPage(e.clientX,e.clientY,svg.getBoundingClientRect(),page.width,page.height);
 function down(e:PointerEvent,id='',handle='move'){
   if(e.button!==0)return;
   if(tool==='pan'){pan={x:e.clientX,y:e.clientY,left:container.scrollLeft,top:container.scrollTop};container.setPointerCapture(e.pointerId);return;}
   if(tool==='add'){drag={id:'new',handle:'new',start:point(e),box:[]};draft=normalizedBox(point(e),point(e));svg.setPointerCapture(e.pointerId);return;}
   if(!id)return;
   e.stopPropagation();onSelect(id,e.shiftKey||e.metaKey||e.ctrlKey);
   if(e.shiftKey||e.metaKey||e.ctrlKey)return;
   const region=regions.find(r=>r.id===id)!;
   drag={id,handle,start:point(e),box:[...region.bbox]};draft=[...region.bbox];svg.setPointerCapture(e.pointerId);
 }
 function move(e:PointerEvent){
   if(pan){container.scrollLeft=pan.left-(e.clientX-pan.x);container.scrollTop=pan.top-(e.clientY-pan.y);return;}
   if(!drag)return;
   const p=point(e),dx=p[0]-drag.start[0],dy=p[1]-drag.start[1];
   if(drag.handle==='new'){draft=normalizedBox(drag.start,p);return;}
   let b=[...drag.box];
   if(drag.handle==='move'){
     const x=Math.max(-b[0],Math.min(page.width-b[2],dx)),y=Math.max(-b[1],Math.min(page.height-b[3],dy));
     b=[b[0]+x,b[1]+y,b[2]+x,b[3]+y];
   }else{
     if(drag.handle.includes('w'))b[0]=Math.min(p[0],b[2]-1);
     if(drag.handle.includes('e'))b[2]=Math.max(p[0],b[0]+1);
     if(drag.handle.includes('n'))b[1]=Math.min(p[1],b[3]-1);
     if(drag.handle.includes('s'))b[3]=Math.max(p[1],b[1]+1);
   }
   draft=b;
 }
 function up(){
   pan=null;
   if(drag&&draft&&draft[2]-draft[0]>=1&&draft[3]-draft[1]>=1){
     if(drag.id==='new'){onCreate(draft);tool='select';}
     else if(draft.some((v,i)=>Math.abs(v-drag!.box[i])>.02))onEdit(drag.id,draft);
   }
   drag=null;draft=null;
 }
 function box(r:Region){return drag?.id===r.id&&draft?draft:r.bbox;}
 const handles=['nw','n','ne','e','se','s','sw','w'];
 function handlePos(b:number[],handle:string){return [handle.includes('w')?b[0]:handle.includes('e')?b[2]:(b[0]+b[2])/2,handle.includes('n')?b[1]:handle.includes('s')?b[3]:(b[1]+b[3])/2];}
</script>

<div class="viewer-head"><div><span class="muted">Page</span> <strong>{page.number}</strong><span class="divider">/</span><span class="muted">{regions.length} regions</span></div><div class="button-group"><button title="Zoom out" aria-label="Zoom out" onclick={()=>zoom=Math.max(.25,zoom-.25)}><ZoomOut size={16}/></button><span class="zoom-value">{Math.round(zoom*100)}%</span><button title="Zoom in" aria-label="Zoom in" onclick={()=>zoom=Math.min(6,zoom+.25)}><ZoomIn size={16}/></button><button title="Fit page" aria-label="Fit page" onclick={()=>{zoom=1;resize();}}><Maximize size={15}/></button><button title="Fit width" onclick={()=>zoom=(container.clientWidth-72)/page.width/fit}>Width</button></div></div>
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class:pan-mode={tool==='pan'} class:add-mode={tool==='add'} class="canvas-scroller" bind:this={container} onpointermove={move} onpointerup={up} onpointercancel={()=>{drag=null;draft=null;pan=null;}} onpointerdown={(e)=>{if(tool==='pan')down(e);}}>
 <div class="page-stage" style:width={`${Math.max(1,page.width*fit*zoom)}px`} style:height={`${Math.max(1,page.height*fit*zoom)}px`}>
  <img class="page-image" src={`/api/jobs/${jobId}/pages/${page.number}/preview`} alt={`PDF page ${page.number}`} draggable="false"/>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <svg bind:this={svg} viewBox={`0 0 ${page.width} ${page.height}`} class="crop-overlay" onpointerdown={(e)=>down(e)} aria-label="Interactive photograph crops">
   {#if overlays}
    {#each regions as r (r.id)}
     {@const b=box(r)}{@const active=selected.includes(r.id)}
     <g class:selected={active} class={`region ${r.status}`}>
      <rect x={b[0]} y={b[1]} width={b[2]-b[0]} height={b[3]-b[1]} class="crop-rect" onpointerdown={(e)=>down(e,r.id)} role="button" tabindex="0" aria-label={`Photograph ${r.ordinal}, ${r.status}`} onkeydown={(e)=>{if(e.key==='Enter')onSelect(r.id);}}/>
      <rect x={b[0]} y={b[1]} width={25/(fit*zoom)} height={23/(fit*zoom)} class="crop-label" pointer-events="none"/>
      <text x={b[0]+12/(fit*zoom)} y={b[1]+16/(fit*zoom)} text-anchor="middle" font-size={12/(fit*zoom)} fill="white" pointer-events="none">{r.ordinal}</text>
      {#if active&&tool==='select'}
       {#each handles as handle}{@const pos=handlePos(b,handle)}
        <rect x={pos[0]-3.5/(fit*zoom)} y={pos[1]-3.5/(fit*zoom)} width={7/(fit*zoom)} height={7/(fit*zoom)} class="crop-handle" style:cursor={`${handle}-resize`} onpointerdown={(e)=>down(e,r.id,handle)} role="button" tabindex="-1" aria-label={`Resize ${handle}`}/>
       {/each}
      {/if}
     </g>
    {/each}
   {/if}
   {#if drag?.id==='new'&&draft}<rect class="new-crop" x={draft[0]} y={draft[1]} width={draft[2]-draft[0]} height={draft[3]-draft[1]}/>{/if}
  </svg>
 </div>
</div>
<div class="viewer-toolbar"><div class="toolbar-cluster">
 {#each [{id:'select',icon:MousePointer2,label:'Select and adjust crops'},{id:'pan',icon:Hand,label:'Pan page'},{id:'add',icon:Plus,label:'Draw new crop'}] as item}
  <button class:active={tool===item.id} title={item.label} aria-label={item.label} onclick={()=>tool=item.id}><item.icon size={17}/></button>
 {/each}
 <span class="tool-separator"></span><button title="Split selected crop vertically" aria-label="Split selected crop" disabled={selected.length!==1} onclick={onSplit}><Columns2 size={17}/></button><button title="Merge selected crops" aria-label="Merge selected crops" disabled={selected.length<2} onclick={onMerge}><Merge size={17}/></button>
 <span class="tool-separator"></span><button title="Undo (⌘Z)" aria-label="Undo" onclick={()=>onHistory(false)}><Undo2 size={17}/></button><button title="Redo (⌘⇧Z)" aria-label="Redo" onclick={()=>onHistory(true)}><Redo2 size={17}/></button><button title="Toggle overlays" aria-label="Toggle overlays" onclick={()=>overlays=!overlays}>{#if overlays}<Eye size={17}/>{:else}<EyeOff size={17}/>{/if}</button>
 </div><span class="tool-hint">{tool==='add'?'Drag to draw a photograph boundary':tool==='pan'?'Drag to pan the page':'Drag an edge to adjust · Shift-click to select multiple'}</span></div>
