<script setup lang="ts">
defineProps<{name:string;size?:number}>()
const paths:Record<string,string>={
 search:'m21 21-4.4-4.4M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0',
 graph:'M8 7l8 3M7 9l2 8m7-4-5 5M8 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0m14 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0m-10 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
 book:'M4 4h7a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H4V4Zm16 0h-3a3 3 0 0 0-3 3v14a4 4 0 0 1 4-2h2V4Z',
 arrow:'M5 12h14m-5-5 5 5-5 5',chevron:'m9 5 7 7-7 7',down:'m6 9 6 6 6-6',close:'m6 6 12 12M6 18 18 6',
 shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Zm-4 9 3 3 5-6',
 logout:'M9 5H4v14h5m7-14 6 7-6 7M8 12h14',user:'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M4 21v-2a8 8 0 0 1 16 0v2',
 refresh:'M20 7v5h-5M4 17v-5h5m-5-1a8 8 0 0 1 14-6l2 3M4 16l2 3a8 8 0 0 0 14-6',
 zoomIn:'M12 5v14M5 12h14',zoomOut:'M5 12h14',fit:'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5',
 info:'M12 10v7m0-11v1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
 layers:'m12 3 10 5-10 5L2 8l10-5Zm-9 9 9 5 9-5M3 16l9 5 9-5',
 clock:'M12 7v5l3 2m7-2a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
 menu:'M3 6h18M3 12h18M3 18h18',check:'m5 12 4 4L19 6',folder:'M3 6h6l2 2h10v12H3V6Z',
 dots:'M5 12h.01M12 12h.01M19 12h.01',external:'M14 3h7v7m0-7L10 14M10 3H3v18h18v-7',
}
</script>
<template><svg :width="size??18" :height="size??18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name]??paths.info"/></svg></template>
