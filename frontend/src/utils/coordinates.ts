export function toPage(clientX:number,clientY:number,rect:{left:number;top:number;width:number;height:number},width:number,height:number):[number,number]{
 return [Math.max(0,Math.min(width,(clientX-rect.left)/rect.width*width)),Math.max(0,Math.min(height,(clientY-rect.top)/rect.height*height))];
}
export function normalizedBox(a:number[],b:number[]):number[]{return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];}
