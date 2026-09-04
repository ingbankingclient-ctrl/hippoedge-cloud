import {copyFile, readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';

const indexPath=join(process.cwd(),'dist','index.html');
let html=await readFile(indexPath,'utf8');
const metadata=`
  <meta name="theme-color" content="#C9A84C">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="HippoEdge">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/icon-180.png">
`;

if(!html.includes('manifest.webmanifest')){
  html=html.replace('</head>',`${metadata}</head>`);
}
await writeFile(indexPath,html,'utf8');

for(const filename of ['manifest.webmanifest','icon-180.png','icon-512.png']){
  await copyFile(join(process.cwd(),'public',filename),join(process.cwd(),'dist',filename));
}
