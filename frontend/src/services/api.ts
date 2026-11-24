let token='';
export function setToken(value:string){token=value;}
export async function api<T=any>(path:string,options:RequestInit={}):Promise<T>{
 const response=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json','X-Local-Token':token,...options.headers}});
 if(!response.ok){let message;try{message=(await response.json()).detail;}catch{message=response.statusText;}throw new Error(typeof message==='string'?message:JSON.stringify(message));}
 return response.json();
}
export function post<T=any>(path:string,body:unknown):Promise<T>{return api(path,{method:'POST',body:JSON.stringify(body)});}
export function upload(file:File,mode:string,password:string,progress:(value:number)=>void):Promise<any>{
 return new Promise((resolve,reject)=>{const req=new XMLHttpRequest();req.open('POST','/api/jobs');req.setRequestHeader('X-Local-Token',token);req.setRequestHeader('X-Filename',encodeURIComponent(file.name));req.setRequestHeader('X-Mode',mode);if(password)req.setRequestHeader('X-PDF-Password',encodeURIComponent(password));req.upload.onprogress=e=>{if(e.lengthComputable)progress(e.loaded/e.total*100);};req.onload=()=>{let data;try{data=JSON.parse(req.responseText);}catch{reject(new Error('Upload returned an invalid response.'));return;}if(req.status>=400)reject(new Error(data.detail));else resolve(data);};req.onerror=()=>reject(new Error('Upload failed. Check the local server.'));req.send(file);});
}
