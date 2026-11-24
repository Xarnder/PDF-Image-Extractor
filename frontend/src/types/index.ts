export type Status='accepted'|'review'|'rejected';
export interface Region {id:string;job_id:string;page:number;ordinal:number;bbox:number[];original_bbox:number[];status:Status;manual:boolean;source:null|{xref:number;width:number;height:number;safe:boolean;encoding:string};dimensions:number[];method:string;confidence:number|null;classification:string;reasons:string[];duplicate:null|{id:string;page:number;kind:string};revision:number;}
export interface Page {number:number;width:number;height:number;status:string;error:string|null;photographs:number;review:number;}
export interface Job {id:string;name:string;total:number;processed:number;status:string;stage:string;photographs:number;counts:Record<string,number>;failed:number;elapsed:number;eta:number|null;speed:number;device:string;engines:string[];warnings:string[];error:string|null;settings:Settings;created:number;}
export interface Settings {[key:string]:any;mode:string;format:string;theme:string;}
