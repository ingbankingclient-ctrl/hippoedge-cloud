import AsyncStorage from '@react-native-async-storage/async-storage';
import type {Meeting,Analysis} from './types';

const KEY='hippoedge_api_url';
const DEFAULT_API_URL=(process.env.EXPO_PUBLIC_API_URL || 'http://127.0.0.1:8000').replace(/\/$/,'');
export async function getBaseUrl(){return (await AsyncStorage.getItem(KEY)) || DEFAULT_API_URL;}
export async function setBaseUrl(v:string){await AsyncStorage.setItem(KEY,v.replace(/\/$/,''));}
async function req<T>(path:string, init?:RequestInit):Promise<T>{
  const base=await getBaseUrl();
  const r=await fetch(base+path,{...init,headers:{'Content-Type':'application/json',...(init?.headers||{})}});
  if(!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
export const Api={
  tomorrow:()=>req<Meeting[]>('/api/tomorrow'),
  program:(day:string)=>req<Meeting[]>(`/api/program/${day}`),
  selections:(day:string)=>req<any>(`/api/day/${day}/selections`),
  analyzeSelections:(day:string,signal?:AbortSignal)=>req<any>(`/api/day/${day}/analyze-selections`,{method:'POST',signal}),
  historyStatus:(day:string)=>req<any>(`/api/day/${day}/history-status`),
  dashboard:(day:string)=>req<any>(`/api/day/${day}/dashboard`),
  queue:(day:string)=>req<any>(`/api/day/${day}/queue`),
  prepareDay:(day:string)=>req<any>(`/api/day/${day}/prepare`,{method:'POST'}),
  refresh:(day:string)=>req<any>(`/api/refresh?day=${day}`,{method:'POST'}),
  analysis:(id:number,force=false)=>req<Analysis>(`/api/races/${id}/analysis?force=${force}`),
  analyzeRace:(id:number,signal?:AbortSignal)=>req<Analysis>(`/api/races/${id}/analyze`,{method:'POST',signal}),
  lock:(id:number)=>req<any>(`/api/races/${id}/lock`,{method:'POST'}),
  stats:()=>req<any>('/api/stats'),
  health:()=>req<any>('/health')
};
