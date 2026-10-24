// Renders the LNZ mask (shared/src/brand.ts) to SVG assets and Chrome extension PNG icons.
import { Resvg } from '@resvg/resvg-js';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const brand = readFileSync(`${root}shared/src/brand.ts`, 'utf8');
const body = brand.slice(brand.indexOf('MASK_PATH ='), brand.indexOf(';', brand.indexOf('MASK_PATH =')));
const path = [...body.matchAll(/'([^']+)'/g)].map((m) => m[1]).join('');
if (!path.startsWith('M')) throw new Error('Could not read MASK_PATH from shared/src/brand.ts');

const CYAN = '#00DDEB';
const filled = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path fill="${CYAN}" fill-rule="evenodd" d="${path}"/></svg>`;
const outline = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path fill="none" stroke="#91A0AF" stroke-width="4.5" stroke-linejoin="round" fill-rule="evenodd" d="${path}"/></svg>`;
// Toolbar/app icon: cyan mask on a dark rounded tile for legibility on light and dark toolbars.
const tile = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="24" fill="#080C10"/><g transform="translate(9 8) scale(0.82)"><path fill="${CYAN}" fill-rule="evenodd" d="${path}"/></g></svg>`;

mkdirSync(`${root}assets`, { recursive: true });
writeFileSync(`${root}assets/lnz-mask.svg`, filled);
writeFileSync(`${root}assets/lnz-mask-outline.svg`, outline);
writeFileSync(`${root}assets/lnz-icon.svg`, tile);

mkdirSync(`${root}extension/public/icons`, { recursive: true });
for (const size of [16, 32, 48, 128]) {
  const png = new Resvg(tile, { fitTo: { mode: 'width', value: size } }).render().asPng();
  writeFileSync(`${root}extension/public/icons/icon${size}.png`, png);
}
writeFileSync(`${root}assets/lnz-mask-512.png`, new Resvg(filled, { fitTo: { mode: 'width', value: 512 } }).render().asPng());
console.log('icons: assets/*.svg, assets/lnz-mask-512.png, extension/public/icons/icon{16,32,48,128}.png');
